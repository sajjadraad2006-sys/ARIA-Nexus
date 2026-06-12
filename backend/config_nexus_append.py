# =====================================================================
#  config_nexus_append.py
#  Bridges the REAL config.py NEXUS_* settings into the Nexus blueprint.
#  nexus_routes_additions.py does:  `import config_nexus_append as NX`
#  Without this file it falls back to hard-coded defaults and IGNORES
#  your customizations in config.py. With it, everything you edit in
#  config.py (services, ports, RAG defaults, web-action path, etc.) is used.
# =====================================================================
from config import *  # noqa: F401,F403
