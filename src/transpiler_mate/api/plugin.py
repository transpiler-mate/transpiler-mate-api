# Copyright 2026 Terradue
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Framework-independent plugin contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import (
    TYPE_CHECKING,
    Annotated,
    Generic,
    Protocol,
    TypeVar,
    runtime_checkable,
)

from cwl_utils.parser import Process
from pydantic import AnyUrl, BaseModel, ConfigDict, Field

from transpiler_mate.api.software_application_models import SoftwareApplication

if TYPE_CHECKING:
    from types import UnionType

OptionsT = TypeVar("OptionsT", bound=BaseModel)


class PluginError(Exception):
    """Base class for errors intentionally exposed by a transpiler plugin."""


class PluginExecutionError(PluginError):
    """Unexpected technical error that prevents a plugin from completing."""


class PluginFailureError(PluginError):
    """Expected domain failure reported by an otherwise working plugin."""


@runtime_checkable
class TranspilerContextResolver(Protocol):
    """Resolves a source into an execution context."""

    def resolve(self, location: str) -> TranspilerContext: ...


class TranspilerContext(BaseModel):
    """Resolved CWL input and normalized metadata prepared by a runtime."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    source: Annotated[AnyUrl, Field(description="The input CWL document URL")]
    process_id: Annotated[
        str | None, Field(default=None, description="The Process fragment identifier")
    ] = None
    metadata: Annotated[SoftwareApplication, Field(description="The input CWL document metadata")]
    document: Annotated[
        Mapping[str, Process],
        Field(description="The input CWL document declared Processes"),
    ]

    resolver: Annotated[
        TranspilerContextResolver,
        Field(description="The resolver instance to parse other CWL documents"),
    ]

    @property
    def processes(self) -> Iterable[Process]:
        """Return an immutable iterable view while preserving `document`."""
        return self.document.values()

    def get_processes_by_type(
        self,
        process_type: type[Process] | UnionType,
        process_ids: Iterable[str] | None = None,
        fail_if_empty: bool = True,
    ) -> Iterable[Process]:
        """Return processes matching a process class or runtime union of classes."""

        computed_list: list[Process] = []

        computed_process_ids: Iterable[str] = process_ids or self.document.keys()

        for process_id in computed_process_ids:
            resolved_process: Process | None = self.document.get(process_id, None)

            if resolved_process and isinstance(resolved_process, process_type):
                computed_list.append(resolved_process)

        if not computed_list and fail_if_empty:
            raise PluginExecutionError(
                f"No {process_type}(s) found in input {self.source} CWL document"
            )

        return computed_list

    @property
    def resolved_process(self) -> Process:
        if not self.process_id:
            raise PluginExecutionError(
                f"No #<process-id> specified in input CWL document {self.source}"
            )

        resolved_process: Process | None = self.document.get(self.process_id, None)

        if not resolved_process:
            raise PluginExecutionError(
                f"Process {self.process_id} does not exist in input CWL document {self.source}, only {self.document.keys()} available."
            )

        return resolved_process


class EmptyOptions(BaseModel):
    """Configuration model for a plugin with no parameters."""

    model_config = ConfigDict(extra="forbid")


class PluginRegistration(BaseModel, Generic[OptionsT]):
    """Immutable metadata and execution function for a stateless plugin."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    name: Annotated[str, Field(description="The plugin name")]
    description: Annotated[str, Field(description="The plugin description")]
    options_model: Annotated[
        type[OptionsT], Field(description="The plugin model type for input options")
    ]
    execute: Annotated[
        Callable[[TranspilerContext, OptionsT], None],
        Field(description="The plugin execution method"),
    ]


def transpiler_plugin(
    *,
    name: str,
    description: str,
    options_model: type[OptionsT],
) -> Callable[
    [Callable[[TranspilerContext, OptionsT], None]],
    PluginRegistration[OptionsT],
]:
    """Register a stateless plugin from its typed execution function."""

    def register(
        execute: Callable[[TranspilerContext, OptionsT], None],
    ) -> PluginRegistration[OptionsT]:
        return PluginRegistration(
            name=name,
            description=description,
            options_model=options_model,
            execute=execute,
        )

    return register


@runtime_checkable
class TranspilerPlugin(Protocol[OptionsT]):
    """Public contract implemented by one independently packaged plugin."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def options_model(self) -> type[OptionsT]: ...

    def execute(
        self,
        context: TranspilerContext,
        options: OptionsT,
    ) -> None:
        """Execute without assumptions about CLI, HTTP, workers, or notebooks."""
        ...
