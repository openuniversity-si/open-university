"""The engine's vendor ports and their adapters (D-069 item 7, plan v3.1 R1).

One port per vendor kind besides the forge (whose port is scripts/lib/forge_events.py, M2): the agent provider
(agent.py), the model ladder (model_ladder.py), the CI runner (ci_runner.py) and storage (storage.py). A port is a small
interface plus the factory that picks its adapter from config/registry/providers.json; an adapter module
(<port>_<vendor>.py) is the only file that talks to its vendor. Callers import the port, never an adapter, and the
engine vendor check (scripts/lib/vendor_check.py) fails a vendor call from scripts/ outside its adapter.

Published surface (contract 1.0.0, versioned here until the manifest slot can hold it for a unit without an address; a breaking change goes expand->contract,
P-07). Other units import only these names, and scripts/tests/test_ports_contract.py holds the list:
adapters.storage.open_store, adapters.launcher.adapter, adapters.launcher.LaunchRequest and
vendor_check.check.
"""
