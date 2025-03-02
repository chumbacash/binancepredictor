import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
import requests
from datetime import datetime, timedelta
import sqlite3
import pytz
import logging
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from flask import Flask, render_template
from threading import Thread
import httpx
import asyncio
import json
from pathlib import Path

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Flask app for health checks
app = Flask(__name__)

@app.route('/')
def root():
    return render_template('index.html')

@app.route('/health')
def health_check():
    try:
        # Check database
        db = DatabaseManager(Config.DB_PATH)
        db.get_user_quota(0)
        
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(pytz.utc).isoformat()
        }, 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(pytz.utc).isoformat()
        }, 500

@dataclass
class Config:
    """Configuration class to hold all bot settings"""
    API_BASE: str = os.getenv("API_BASE", "https://binancedata-api.onrender.com")
    DEFAULT_DAILY_LIMIT: int = int(os.getenv("DEFAULT_DAILY_LIMIT", "10"))
    REFERRAL_BONUS: int = int(os.getenv("REFERRAL_BONUS", "5"))
    BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    DB_PATH: str = "data/predictions.db"

class DatabaseManager:
    """Handles all database operations"""
    def __init__(self, db_path: str):
        """Initialize database manager with proper path handling"""
        self.db_path = db_path
        # Ensure data directory exists
        Path(os.path.dirname(db_path)).mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database with proper date handling"""
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                # Create users table if it doesn't exist
                c.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        daily_used INTEGER DEFAULT 0,
                        referrals INTEGER DEFAULT 0,
                        last_updated TEXT DEFAULT (date('now'))
                    )
                ''')
                conn.commit()
                logger.info("Database initialized successfully")
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            # If database is corrupted, recreate it
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new database connection with proper settings"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            logger.error(f"Database connection error: {e}")
            raise

    def get_user_quota(self, user_id: int) -> int:
        """Get remaining predictions for a user with proper error handling"""
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT daily_used, last_updated FROM users WHERE user_id = ?", (user_id,))
                result = c.fetchone()
                
                today = datetime.now(pytz.utc).date().isoformat()
                
                if not result:
                    # Create new user entry
                    c.execute(
                        "INSERT INTO users (user_id, daily_used, last_updated) VALUES (?, 0, ?)",
                        (user_id, today)
                    )
                    conn.commit()
                    return Config.DEFAULT_DAILY_LIMIT
                
                daily_used = result['daily_used']
                last_updated = result['last_updated']
                
                if last_updated < today:
                    # Reset daily quota
                    c.execute(
                        "UPDATE users SET daily_used = 0, last_updated = ? WHERE user_id = ?",
                        (today, user_id)
                    )
                    conn.commit()
                    return Config.DEFAULT_DAILY_LIMIT
                
                return max(0, Config.DEFAULT_DAILY_LIMIT - daily_used)
                
        except sqlite3.Error as e:
            logger.error(f"Error getting user quota: {e}")
            return Config.DEFAULT_DAILY_LIMIT  # Fallback to default limit

    def update_user_predictions(self, user_id: int, count: int = 1) -> None:
        """Update the number of predictions used by a user"""
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                c.execute(
                    "UPDATE users SET daily_used = daily_used + ? WHERE user_id = ?",
                    (count, user_id)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error updating user predictions: {e}")

    def add_referral(self, referrer_id: int) -> None:
        """Add referral bonus to user"""
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                c.execute(
                    """UPDATE users 
                       SET referrals = referrals + 1,
                           daily_used = CASE 
                               WHEN daily_used >= ? THEN daily_used - ?
                               ELSE 0
                           END
                       WHERE user_id = ?""",
                    (Config.REFERRAL_BONUS, Config.REFERRAL_BONUS, referrer_id)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error adding referral: {e}")

class CryptoBot:
    """Main bot class handling all Telegram interactions"""
    def __init__(self):
        if not Config.BOT_TOKEN:
            raise ValueError("ERROR: Telegram token not found in .env file!")
            
        self.db = DatabaseManager(Config.DB_PATH)
        self.app = ApplicationBuilder().token(Config.BOT_TOKEN).build()
        self._setup_handlers()
        self._start_health_server()

    def _start_health_server(self):
        """Start a minimal HTTP server for health checks"""
        port = int(os.getenv("PORT", "8080"))  # Use PORT env var or default to 8080
        logger.info(f"Starting health check server on port {port}")
        Thread(
            target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False),
            daemon=True
        ).start()

    async def _fetch_prediction(self, symbol: str, timeframe: str) -> Optional[dict]:
        """Fetch prediction directly using httpx"""
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                url = f"{Config.API_BASE}/predict/{symbol}"
                params = {"interval": timeframe}
                headers = {
                    "Accept": "application/json",
                    "User-Agent": "curl/8.4.0"
                }
                
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                if not data:
                    logger.warning("Empty response received")
                    return None
                    
                return data
        except Exception as e:
            logger.error(f"Error fetching prediction: {e}")
            return None

    def _format_prediction_message(self, data: dict, symbol: str, timeframe: str, remaining: int) -> str:
        """Format the prediction message with comprehensive analysis"""
        try:
            def parse_price(price_str):
                """Helper to parse price strings that might contain $ or commas"""
                if isinstance(price_str, (int, float)):
                    return float(price_str)
                # Extract numeric value if string contains a price
                if '$' in str(price_str):
                    price_part = str(price_str).split('$')[1].split()[0]
                    return float(price_part.replace(',', ''))
                return float(str(price_str).replace(',', ''))
            
            metadata = data['metadata']
            price_analysis = data['price_analysis']
            ai_insights = data.get('ai_insights', {})
            frontend_insights = data.get('frontend_insights', {})
            
            # Determine quote currency for price formatting
            quote_currency = ""
            for stable in ["USDT", "USDC", "FDUSD"]:
                if symbol.endswith(stable):
                    quote_currency = "$"
                    break
            if not quote_currency:
                # For non-stablecoin pairs, use the last 3-4 characters as quote currency
                quote_currency = symbol[-3:] if len(symbol) >= 6 else symbol[-4:]
                quote_currency = f"{quote_currency} "
            
            # Format confidence indicator
            confidence = metadata['confidence_score']
            confidence_emoji = "🟢" if confidence > 0.8 else "🟡" if confidence > 0.6 else "🔴"
            
            # Calculate time ago
            last_updated = datetime.fromisoformat(metadata['last_updated'].replace('Z', '+00:00'))
            time_ago = datetime.now(pytz.utc) - last_updated
            
            if time_ago.total_seconds() < 60:
                update_text = "just now"
            else:
                minutes_ago = int(time_ago.total_seconds() / 60)
                update_text = f"{minutes_ago} minutes ago" if minutes_ago < 60 else f"{minutes_ago // 60} hours ago"
            
            # Calculate price change
            current_price = parse_price(price_analysis['current'])
            predicted_price = parse_price(price_analysis['prediction'])
            price_change = predicted_price - current_price
            change_percent = (price_change / current_price) * 100
            direction = "📈" if price_change > 0 else "📉"
            
            # Get moving averages
            sma_20 = parse_price(price_analysis.get('sma_20', 0))
            sma_50 = parse_price(price_analysis.get('sma_50', 0))
            
            # Get key levels
            key_levels = price_analysis.get('key_levels', {})
            support = parse_price(key_levels.get('support', 0))
            resistance = parse_price(key_levels.get('resistance', 0))
            trend_strength = float(key_levels.get('trend_strength', 0))
            
            # Format MACD data if available
            macd_data = price_analysis.get('macd', {})
            macd_trend = ""
            if macd_data:
                macd_line = macd_data.get('macd_line', [])
                signal_line = macd_data.get('signal_line', [])
                if macd_line and signal_line:
                    current_macd = float(macd_line[-1])
                    current_signal = float(signal_line[-1])
                    macd_trend = "🟢 Bullish" if current_macd > current_signal else "🔴 Bearish"
            
            # Get trading recommendations
            trading_recs = ai_insights.get('trading_recommendations', [])
            rec_text = ""
            if trading_recs:
                main_rec = trading_recs[0]
                rec_text = (
                    f"\n💡 *Recommended Action:* {main_rec.get('action')}\n"
                    f"Entry: {main_rec.get('entry')}\n"
                    f"Exit: {main_rec.get('exit')}\n"
                )
            
            # Get risk factors
            risk_factors = ai_insights.get('risk_factors', [])
            risk_text = "\n⚠️ *Risk Factors:*\n" + "\n".join(f"• {risk}" for risk in risk_factors[:2]) if risk_factors else ""
            
            # Format price with appropriate precision based on value
            def format_price(price):
                if price < 0.0001:
                    return f"{price:.8f}"
                elif price < 0.01:
                    return f"{price:.6f}"
                elif price < 1:
                    return f"{price:.4f}"
                else:
                    return f"{price:,.2f}"
            
            # Format the message
            message = (
                f"*{symbol} Price Analysis* {direction}\n"
                f"Timeframe: {timeframe}\n"
                f"─────────────────\n\n"
                f"💰 Current Price: {quote_currency}{format_price(current_price)}\n"
                f"🎯 Predicted Price: {quote_currency}{format_price(predicted_price)} ({change_percent:+.2f}%)\n"
                f"📊 Range: {quote_currency}{format_price(parse_price(price_analysis['prediction_range']['low']))} - "
                f"{quote_currency}{format_price(parse_price(price_analysis['prediction_range']['high']))}\n\n"
                f"📈 *Technical Analysis*\n"
                f"• RSI: {price_analysis['rsi']:.1f}\n"
                f"• Volatility: {price_analysis['volatility']*100:.2f}%\n"
                f"• MACD: {macd_trend}\n"
                f"• SMA20: {quote_currency}{format_price(sma_20)}\n"
                f"• SMA50: {quote_currency}{format_price(sma_50)}\n\n"
                f"📍 *Key Levels*\n"
                f"• Support: {quote_currency}{format_price(support)}\n"
                f"• Resistance: {quote_currency}{format_price(resistance)}\n"
                f"• Trend Strength: {trend_strength*100:.1f}%\n"
            )
            
            # Add AI insights if available
            if ai_insights.get('market_summary'):
                message += f"\n📊 *Market Summary*\n{ai_insights['market_summary']}\n"
            
            # Add trading recommendation
            if rec_text:
                message += rec_text
            
            # Add risk factors
            if risk_text:
                message += risk_text
            
            # Add confidence and data quality
            message += (
                f"\n─────────────────\n"
                f"{confidence_emoji} Confidence: {int(confidence*100)}%\n"
                f"📊 Data Quality: {int(metadata['data_quality']*100)}%\n"
                f"🕒 Updated: {update_text}\n"
                f"📊 Predictions Left: {remaining-1}"
            )
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting prediction message: {e}")
            return "⚠️ Error formatting prediction data"

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        user = update.effective_user
        
        # Handle referral
        if context.args and context.args[0].startswith('ref_'):
            try:
                referrer_id = int(context.args[0].split('_')[1])
                if referrer_id != user.id:
                    self.db.add_referral(referrer_id)
            except (ValueError, IndexError):
                logger.warning(f"Invalid referral format: {context.args[0]}")

        keyboard = [
            [InlineKeyboardButton("🔮 Get Predictions", callback_data="get_predictions")],
            [InlineKeyboardButton("👥 Refer Friends", callback_data="show_referral")]
        ]
        
        await update.message.reply_text(
            f"👋 Welcome {user.first_name}!\n\n"
            "📊 I provide crypto price predictions using advanced AI models.\n"
            f"📌 You have {Config.DEFAULT_DAILY_LIMIT} free predictions today.\n\n"
            "🎁 Invite friends to get more predictions!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle menu button callbacks"""
        query = update.callback_query
        await query.answer()

        if query.data == "get_predictions":
            await query.edit_message_text(
                "🔍 Send me a trading pair like BTCUSDT to get started!\n\n"
                "Popular pairs:\n"
                "• BTCUSDT (Bitcoin)\n"
                "• ETHUSDT (Ethereum)\n"
                "• SOLUSDT (Solana)"
            )
        elif query.data == "show_referral":
            referral_link = f"https://t.me/{context.bot.username}?start=ref_{query.from_user.id}"
            keyboard = [
                [InlineKeyboardButton("📲 Share Link", url=referral_link)],
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
            ]
            
            await query.edit_message_text(
                "🎁 *Referral Program*\n\n"
                f"• Get +{Config.REFERRAL_BONUS} predictions for each friend who joins\n"
                "• Your friend also gets bonus predictions\n\n"
                "Share your referral link:\n"
                f"`{referral_link}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        elif query.data == "main_menu":
            keyboard = [
                [InlineKeyboardButton("🔮 Get Predictions", callback_data="get_predictions")],
                [InlineKeyboardButton("👥 Refer Friends", callback_data="show_referral")]
            ]
            
            await query.edit_message_text(
                "🤖 *Main Menu*\n\n"
                "Choose an option:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

    async def handle_symbol(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming symbol messages"""
        symbol = update.message.text.upper()
        
        # Send typing action
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=constants.ChatAction.TYPING
        )
        
        # Basic format validation
        if len(symbol) < 4 or len(symbol) > 12:
            await update.message.reply_text(
                "❌ Invalid trading pair length.\n\n"
                "Please use valid pairs like:\n"
                "• Stablecoin pairs: BTCUSDT, ETHUSDC, BNBFDUSD\n"
                "• Crypto pairs: ETHBTC, BNBBTC, LRCETH\n"
                "• Fiat pairs: BTCEUR, ETHGBP, BNBTRY"
            )
            return

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Default to common symbols if API check fails
                valid_symbols = [
                    # Stablecoin pairs
                    "BTCUSDT", "ETHUSDT", "BNBUSDT",
                    "BTCUSDC", "ETHUSDC", "BNBUSDC",
                    "BTCFDUSD", "ETHFDUSD", "BNBFDUSD",
                    # Popular crypto pairs
                    "ETHBTC", "BNBBTC", "LRCETH",
                    # Fiat pairs
                    "BTCEUR", "ETHEUR", "BNBEUR"
                ]
                
                try:
                    response = await client.get(f"{Config.API_BASE}/symbols")
                    if response.is_success:
                        data = response.json()
                        if 'symbols' in data and data['symbols']:
                            valid_symbols = data['symbols']
                except Exception as e:
                    logger.warning(f"Failed to fetch symbols, using default list: {e}")

                if symbol not in valid_symbols:
                    await update.message.reply_text(
                        "❌ Unsupported trading pair.\n\n"
                        "Popular pairs you can try:\n"
                        "• Stablecoin: BTCUSDT, ETHUSDC, BNBFDUSD\n"
                        "• Crypto: ETHBTC, BNBBTC, LRCETH\n"
                        "• Fiat: BTCEUR, ETHEUR, BNBTRY"
                    )
                    return

        except Exception as e:
            logger.error(f"Error in symbol validation: {e}")
            # Continue with the request even if symbol validation fails
            pass

        # Get user quota
        user_id = update.effective_user.id
        remaining = self.db.get_user_quota(user_id)
        
        if remaining <= 0:
            keyboard = [[
                InlineKeyboardButton(
                    "👥 Get More Predictions",
                    callback_data="show_referral"
                )
            ]]
            await update.message.reply_text(
                "🚫 Daily limit reached!\n\n"
                "💡 Get more predictions by inviting friends.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Show "calculating" message while fetching prediction
        calculating_message = await update.message.reply_text(
            "🔄 Calculating prediction...\n"
            "This may take a few moments."
        )

        try:
            # Fetch prediction
            prediction_data = await self._fetch_prediction(symbol, "1h")
            
            if prediction_data:
                # Update user quota
                self.db.update_user_predictions(user_id)
        except Exception as e:
            logger.error(f"Error in handle_symbol: {e}")
            prediction_data = None

        # Delete the calculating message
        await calculating_message.delete()

        if not prediction_data:
            await update.message.reply_text(
                "⚠️ Unable to generate prediction.\n\n"
                "This could be due to:\n"
                "1. Temporary API issues\n"
                "2. High server load\n"
                "3. Market data unavailability\n\n"
                "Please try again in a few moments."
            )
            return

        try:
            message = self._format_prediction_message(prediction_data, symbol, "1h", remaining)
            
            keyboard = [[
                InlineKeyboardButton("👥 Refer Friends", callback_data="show_referral")
            ]]
            
            await update.message.reply_text(
                text=message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error sending prediction: {e}")
            await update.message.reply_text(
                "⚠️ Error displaying prediction.\n"
                "Please try again."
            )

    def _setup_handlers(self) -> None:
        """Set up all message handlers"""
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_symbol
        ))
        self.app.add_handler(CallbackQueryHandler(self.handle_menu_callback))

    def run(self) -> None:
        """Run the bot"""
        self.app.run_polling()

if __name__ == "__main__":
    # Initialize and run the bot
    try:
        bot = CryptoBot()
        logger.info("Bot started successfully!")
        bot.app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")