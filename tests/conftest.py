"""Suite-wide test isolation.

Settings reads the developer's own .env. An operator key set there for running
the app locally would otherwise switch authentication on for every test that
builds default Settings, and those tests would fail with 401 on one machine and
pass in CI. Tests that exercise auth pass their keys explicitly.

Set here, at import, so it is in place before any app or Settings is built. A
real environment variable outranks .env, and an empty one means auth is off.
"""
import os

os.environ["VOXGATE_API_KEYS"] = ""
