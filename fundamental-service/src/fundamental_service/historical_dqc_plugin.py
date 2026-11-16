"""Arelle discovery adapter for the Fundamental historical DQC runtime."""

from arelle.CntlrCmdLine import CntlrCmdLine, ParserForDynamicPlugins
from arelle.RuntimeOptions import RuntimeOptions
from arelle.ValidateXbrl import ValidateXbrl

from fundamental_service import historical_dqc


def options(parser: ParserForDynamicPlugins) -> None:
    historical_dqc.options(parser)


def initialize(
    controller: CntlrCmdLine, runtime: RuntimeOptions, **kwargs: object
) -> None:
    historical_dqc.initialize(controller, runtime, **kwargs)


def validate(validation: ValidateXbrl) -> None:
    historical_dqc.validate(validation)


__pluginInfo__ = {
    "name": "Fundamental official historical DQC adapter",
    "version": "1.0.0",
    "CntlrCmdLine.Options": options,
    "CntlrCmdLine.Utility.Run": initialize,
    "Validate.XBRL.Finally": validate,
}
