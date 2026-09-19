# Forwarder Telegram - Windows Executable

## Quick Start

1. **Place these files in the same folder:**
   - `forwarder-telegram.exe` (the executable)
   - `config.json` (your configuration file)
   - `.env` (optional, if you use environment variables)
   - `forwarder_session.session` (will be created after first run)

2. **Configure config.json:**
   ```json
   {
     "api_id": 1234567,
     "api_hash": "your_api_hash_here",
     "source_channels": {
       "-1001892345740": "Channel Name 1",
       "-1001327949777": "Channel Name 2"
     },
     "target_group": -1002619945550
   }
   ```

3. **Run the executable:**
   - Double-click `forwarder-telegram.exe`
   - Or run from command line: `.\forwarder-telegram.exe`

4. **First run:**
   - Enter your phone number when prompted
   - Enter the verification code from Telegram
   - The session file will be saved for future runs

## Files Created by the Application

The executable will create/use these files in the same folder:
- `config.json` - Configuration file (required)
- `forwarder_session.session` - Telegram session (auto-created)
- `forwarded_messages.json` - Message tracking (auto-created)
- `logs.txt` - Application logs (auto-created)

## Environment Variables (Optional)

You can set `TG_PHONE` in a `.env` file to avoid entering phone number each time:
```
TG_PHONE=+1234567890
```

## Notes

- The executable looks for all configuration files in its own directory
- Keep the executable and config files together
- Session file contains your authentication - keep it secure
- Check `logs.txt` for detailed application logs
