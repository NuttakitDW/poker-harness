voice: 
	.venv/bin/python scripts/voice/ask.py --live
chart: 
	.venv/bin/python scripts/voice/spot_chart.py
bot: 
	.venv/bin/python scripts/discord_bot/bot.py
bot-review: 
	.venv/bin/python scripts/discord_bot/question_log.py
web: 
	.venv/bin/python scripts/web/server.py
web-watch: 
	.venv/bin/python scripts/web/watch.py
web-review: 
	.venv/bin/python scripts/discord_bot/question_log.py web
method: 
	.venv/bin/python scripts/web/method.py
spot-eval: 
	.venv/bin/python scripts/voice/spot_eval.py --failures
record-spots: 
	.venv/bin/python scripts/voice/record_spots.py
