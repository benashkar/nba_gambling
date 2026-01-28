@echo off
cd /d "C:\Users\cashk\OneDrive\Projects\NBAGambling"
python run_player_props.py --compare >> logs\player_props_scheduled.log 2>&1
