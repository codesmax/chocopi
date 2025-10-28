-- Disable logind integration for headless service operation
-- Allows Bluetooth to work without a logged-in user session
bluez_monitor.properties["with-logind"] = false

-- Prefer headset-head-unit profile for Bluetooth devices
-- This enables both microphone and speaker (HSP/HFP) instead of
-- the default of high-quality playback only (A2DP)
table.insert(bluez_monitor.rules, {
  matches = {
    {
      { "device.name", "matches", "bluez_card.*" },
    },
  },
  apply_properties = {
    ["device.profile"] = "headset-head-unit",
  },
})
