voice: 
	.venv/bin/python scripts/voice/ask.py --live
chart: 
	.venv/bin/python scripts/voice/spot_chart.py
bot: 
	.venv/bin/python scripts/discord_bot/bot.py
bot-review: 
	.venv/bin/python scripts/discord_bot/question_log.py
spot-eval: 
	.venv/bin/python scripts/voice/spot_eval.py --failures
