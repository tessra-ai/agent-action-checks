import os

# litellm (imported by tau2) fetches its model price map over the network at import unless told
# to use the bundled copy.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
