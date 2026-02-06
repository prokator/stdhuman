@echo off
python -c "from app.start_code import initialize_auth_files, get_start_code; initialize_auth_files(); print(f'/start {get_start_code()}')"
