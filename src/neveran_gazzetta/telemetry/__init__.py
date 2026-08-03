"""Telemetria fail-open, priva di contenuti narrativi o segreti."""

from neveran_gazzetta.telemetry.monitor import MonitorTelemetry, NullTelemetry, TelemetrySink

__all__ = ["MonitorTelemetry", "NullTelemetry", "TelemetrySink"]
