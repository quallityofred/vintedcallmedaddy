# Vinted Monitor Bot 🤖

Professional tool for monitoring Vinted listings with Telegram notifications and a web dashboard.

## Key Features
- **Live Monitoring**: Track multiple search links with adaptive intervals.
- **Deduplication**: Atomic database-level deduplication (protection against duplicates).
- **Dashboard**: FastAPI-based web interface with live logs console and real-time statistics.
- **Cloud-Ready**: Fully optimized for cloud environments (Railway, Render) with PostgreSQL (Supabase/Neon) support, using SSL and Transaction Mode.

## Quick Start
1. Clone the repository: 
   ```bash
   git clone https://github.com/tellaboutme/vintedbot
   cd vintedbot
   ```
2. Set up your configuration: `cp .env.example .env`
3. Install dependencies: `poetry install`
4. Run the application: `poetry run uvicorn app.main:app`

## Production
The project is optimized for Docker containers. For cloud databases (Supabase/Neon), ensure you use port 6543 and enable SSL in your connection string.

## License
MIT
