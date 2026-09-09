import os

# Importing MultiWorldGG's `worlds` package (e.g. via `worlds.AutoWorld`)
# triggers its ModuleUpdate machinery, which otherwise shells out to `pip
# install` for every other world's requirements.txt on collection. See
# PLAN.md's M0 notes and MultiWorldGG's ModuleUpdate.py:70.
os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")
