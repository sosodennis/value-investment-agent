"""Preserve official DQC rule severity before EFM changes log levels."""

from fundamental_service.dqc_diagnostic_plugin import preserve_rule_severity

__pluginInfo__ = {
    "name": "Fundamental official DQC severity",
    "version": "1.0.0",
    "CntlrCmdLine.Xbrl.Loaded": preserve_rule_severity,
}
