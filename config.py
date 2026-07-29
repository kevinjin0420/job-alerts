from __future__ import annotations

# Source kinds build_sources() knows how to construct (see sources/__init__.py)
# and the job-type taxonomy user configs and company records use. Kept here,
# not in sources/, since the dashboard Lambda packages config.py but not sources/.
SUPPORTED_SOURCE_KINDS = ["community", "apple", "google"]
SUPPORTED_JOB_TYPES = ["intern", "newgrad", "fulltime"]
