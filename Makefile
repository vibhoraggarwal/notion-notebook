.DEFAULT_GOAL := help

# ── Setup ────────────────────────────────────────────────────────────────────

install:          ## Install Python dependencies
	pip install -r requirements.txt

setup:            ## Create .env from template (skip if already exists)
	@test -f .env && echo ".env already exists, skipping." || (cp .env.example .env && echo "Created .env — edit it before running.")

# ── Sync ─────────────────────────────────────────────────────────────────────

pull:             ## Download all pages from Notion
	python scripts/pull.py

push:             ## Upload all locally changed pages to Notion
	python scripts/push.py

# ── Weather ──────────────────────────────────────────────────────────────────
# Current weather (uses WEATHER_PAGE from .env):
#   make weather
#
# Date range:
#   make weather PAGE="Easter_in_BW" FROM=2026-04-02 TO=2026-04-06

PAGE     ?=
FROM     ?=
TO       ?=
CITY     ?=
REMEMBER ?=

weather:          ## Update weather in local file  (see: make help-weather)
	@CITY_ARG=""; [ -n "$(CITY)" ] && CITY_ARG="--city $(CITY)"; \
	REM_ARG=""; [ -n "$(REMEMBER)" ] && REM_ARG="--remember"; \
	if [ -n "$(FROM)" ] && [ -n "$(TO)" ]; then \
		python scripts/weather.py "$(PAGE)" $(FROM) $(TO) $$CITY_ARG $$REM_ARG; \
	elif [ -n "$(PAGE)" ]; then \
		python scripts/weather.py "$(PAGE)" $$CITY_ARG $$REM_ARG; \
	else \
		python scripts/weather.py $$CITY_ARG $$REM_ARG; \
	fi

# ── Help ─────────────────────────────────────────────────────────────────────

help:             ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

help-weather:     ## Show detailed weather usage
	@printf "\n\033[1mWeather usage\033[0m\n\n"
	@printf "  \033[36mmake weather\033[0m\n"
	@printf "    Current weather for default page and city (from .env)\n\n"
	@printf "  \033[36mmake weather PAGE=\"My Page\"\033[0m\n"
	@printf "    Current weather for a specific page\n\n"
	@printf "  \033[36mmake weather PAGE=\"My Page\" FROM=2026-04-03 TO=2026-04-06\033[0m\n"
	@printf "    Date range for a specific page\n\n"
	@printf "  \033[36mmake weather PAGE=\"My Page\" FROM=2026-04-03 TO=2026-04-06 CITY=Berlin\033[0m\n"
	@printf "    Date range for a specific city (geocoded automatically)\n\n"
	@printf "  \033[36mmake weather PAGE=\"My Page\" CITY=Berlin REMEMBER=1\033[0m\n"
	@printf "    Save config so push auto-refreshes this table every time\n\n"
	@printf "\033[1mMultiple cities on the same page:\033[0m\n\n"
	@printf "  make weather PAGE=\"My Page\" FROM=2026-04-03 TO=2026-04-06 REMEMBER=1\n"
	@printf "  make weather PAGE=\"My Page\" FROM=2026-04-03 TO=2026-04-06 CITY=Berlin REMEMBER=1\n\n"
	@printf "\033[1mVariables (set in .env):\033[0m\n\n"
	@printf "  WEATHER_PAGE   Default page title\n"
	@printf "  WEATHER_CITY   Default city label (used when no CITY given)\n"
	@printf "  WEATHER_LAT    Default latitude\n"
	@printf "  WEATHER_LON    Default longitude\n"
	@printf "  WEATHER_TZ     Timezone (e.g. Europe/Berlin)\n\n"
