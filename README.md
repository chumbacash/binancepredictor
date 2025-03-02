# 🔷 Binance Predictor Bot

An AI-powered Telegram bot that provides real-time cryptocurrency price predictions and trading insights.

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

## 🚀 Features

- **Real-time Predictions**: Get instant price predictions powered by advanced AI algorithms
- **Multiple Timeframes**: Analysis for different trading intervals
- **Technical Analysis**: Comprehensive indicators including RSI, MACD, and moving averages
- **Key Levels**: Support and resistance levels with trend strength analysis
- **Risk Management**: AI-powered risk assessment and trading recommendations
- **User Quotas**: Daily prediction limits with referral bonuses
- **Secure & Private**: Your trading data stays private and secure

## 🛠️ Tech Stack

- **Python 3.8+**
- **python-telegram-bot**: Telegram bot API wrapper
- **Flask**: Web server for health checks
- **SQLite**: Local database for user management
- **HTTPX**: Async HTTP client for API calls
- **python-dotenv**: Environment variable management

## 📋 Prerequisites

- Python 3.8 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Access to Binance Data API

## ⚙️ Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/chumbacash/binancepredictor.git
   cd binancepredictor
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Unix/MacOS
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   # Create .env file
   cp .env.example .env
   # Edit .env with your configuration
   ```

   Required environment variables:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
   - `API_BASE`: Binance data API base URL
   - `DEFAULT_DAILY_LIMIT`: Number of free predictions per day
   - `REFERRAL_BONUS`: Extra predictions for referrals
   - `PORT`: Web server port (default: 8080)

## 🚀 Usage

1. **Start the bot**
   ```bash
   python app.py
   ```

2. **Access the bot on Telegram**
   - Open [@binancepredictorbot](https://t.me/binancepredictorbot) on Telegram
   - Start chatting with `/start`
   - Send any trading pair (e.g., BTCUSDT) to get predictions

## 📊 Available Commands

- `/start`: Initialize the bot and get welcome message
- `/help`: Display help information
- Send any valid trading pair to get predictions

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🌟 Support

If you find this project helpful, please give it a star on GitHub! 