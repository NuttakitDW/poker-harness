voice: 
	.venv/bin/python scripts/voice/ask.py --live
chart: 
	.venv/bin/python scripts/voice/spot_chart.py
chat: chart
bot: 
	.venv/bin/python scripts/discord_bot/bot.py
bot-review: 
	.venv/bin/python scripts/discord_bot/question_log.py
bot-commands: 
	.venv/bin/python scripts/discord_bot/slash_commands.py $(ARGS)
web: 
	.venv/bin/python scripts/web/server.py
ft: 
	.venv/bin/python scripts/final_table/ft_server.py
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
swarm-setup:
	uv venv -q .venv-swarm --python 3.12 && uv pip install -q --python .venv-swarm/bin/python -r deepstack-swarm/requirements.txt
swarm:
	cd deepstack-swarm && ../.venv-swarm/bin/python -m swarm chat $(ARGS)
swarm-monitor:
	cd deepstack-swarm && ../.venv-swarm/bin/python -m swarm monitor $(ARGS)
swarm-test:
	cd deepstack-swarm && ../.venv-swarm/bin/python -m unittest tests/test_swarm.py
