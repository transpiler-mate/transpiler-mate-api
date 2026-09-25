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

from pathlib import Path
from typing import cast

import pytest
from cwl_utils.parser import Workflow as WorkflowType
from cwl_utils.parser.cwl_v1_0 import Workflow as WorkflowV1_0
from cwl_utils.parser.cwl_v1_2 import CommandLineTool, Workflow
from pydantic import AnyUrl, BaseModel, ValidationError

from transpiler_mate import api
from transpiler_mate.api import (
    EmptyOptions,
    PluginError,
    PluginExecutionError,
    PluginFailureError,
    PluginRegistration,
    TranspilerContext,
    TranspilerContextResolver,
    TranspilerPlugin,
    software_application_models,
    transpiler_plugin,
)
from transpiler_mate.api.software_application_models import SoftwareApplication


class Options(BaseModel):
    output: Path


class Resolver:
    def resolve(self, location: str) -> TranspilerContext:
        raise NotImplementedError


RESOLVER: TranspilerContextResolver = Resolver()


def test_transpiler_plugin_registers_typed_execution_function() -> None:
    executed_with: list[Path] = []

    @transpiler_plugin(
        name="test",
        description="Test registration",
        options_model=Options,
    )
    def plugin(
        context: TranspilerContext,
        options: Options,
    ) -> None:
        executed_with.append(options.output)

    conforms: TranspilerPlugin[Options] = plugin

    assert isinstance(plugin, PluginRegistration)
    assert isinstance(plugin, TranspilerPlugin)
    assert conforms.name == "test"
    assert plugin.description == "Test registration"
    assert plugin.options_model is Options
    context = cast("TranspilerContext", object())
    plugin.execute(context, Options(output=Path("out.txt")))
    assert executed_with == [Path("out.txt")]


def test_plugin_registration_is_an_immutable_pydantic_model() -> None:
    def execute(
        context: TranspilerContext,
        options: Options,
    ) -> None:
        pass

    registration = PluginRegistration(
        name="test", description="Test", options_model=Options, execute=execute
    )

    assert registration.model_dump() == {
        "name": "test",
        "description": "Test",
        "options_model": Options,
        "execute": execute,
    }
    with pytest.raises(ValidationError, match="Instance is frozen"):
        registration.name = "changed"
    assert isinstance(registration, BaseModel)


def test_plugin_registration_forbids_unknown_fields() -> None:
    def execute(
        context: TranspilerContext,
        options: Options,
    ) -> None:
        pass

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PluginRegistration.model_validate(
            {
                "name": "test",
                "description": "Test",
                "options_model": Options,
                "execute": execute,
                "unexpected": True,
            }
        )


def test_empty_options_forbids_configuration() -> None:
    assert EmptyOptions().model_dump() == {}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EmptyOptions.model_validate({"unexpected": True})


def test_plugin_exceptions_share_a_common_base() -> None:
    assert issubclass(PluginExecutionError, PluginError)
    assert issubclass(PluginFailureError, PluginError)


def test_software_application_models_are_exported_from_api() -> None:
    models = {
        name: model
        for name, model in vars(software_application_models).items()
        if isinstance(model, type)
        and issubclass(model, BaseModel)
        and model.__module__ == software_application_models.__name__
    }

    assert models
    for model_name, model in models.items():
        assert model_name in api.__all__
        assert getattr(api, model_name) is model


def test_transpiler_context_is_defined_in_plugin_module() -> None:
    assert TranspilerContext.__module__ == "transpiler_mate.api.plugin"


def test_transpiler_context_is_an_immutable_pydantic_model() -> None:
    process = object()
    processes = {"asd": process}
    context = TranspilerContext.model_construct(
        source=Path("workflow.cwl"),
        document=processes,
        metadata=object(),
        resolver=RESOLVER,
    )

    assert context.document == processes
    with pytest.raises(ValidationError, match="Instance is frozen"):
        context.source = AnyUrl(Path("changed.cwl").absolute().as_uri())
    assert isinstance(context, BaseModel)


def test_transpiler_context_wraps_a_single_process() -> None:
    process = {"asd": Workflow(id="asd", inputs=[], outputs=[], steps=[])}
    context = TranspilerContext(
        source=AnyUrl(Path("workflow.cwl").absolute().as_uri()),
        document=process,
        metadata=SoftwareApplication.model_construct(),
        resolver=RESOLVER,
    )

    assert context.document == process

    for inner_process in context.processes:
        assert inner_process.id in process
        assert inner_process == process[inner_process.id]

    assert context.resolver is RESOLVER


def test_transpiler_context_gets_processes_by_type() -> None:
    first_workflow = Workflow(id="first", inputs=[], outputs=[], steps=[])
    command_line_tool = CommandLineTool(id="tool", inputs=[], outputs=[])
    second_workflow = Workflow(id="second", inputs=[], outputs=[], steps=[])
    context = TranspilerContext(
        source=AnyUrl(Path("workflow.cwl").absolute().as_uri()),
        document={
            "first": first_workflow,
            "tool": command_line_tool,
            "second": second_workflow,
        },
        metadata=SoftwareApplication.model_construct(),
        resolver=RESOLVER,
    )

    processes = context.get_processes_by_type(Workflow)

    assert list(processes) == [first_workflow, second_workflow]


def test_transpiler_context_gets_processes_by_union_type() -> None:
    first_workflow = WorkflowV1_0(id="first", inputs=[], outputs=[], steps=[])
    command_line_tool = CommandLineTool(id="tool", inputs=[], outputs=[])
    second_workflow = Workflow(id="second", inputs=[], outputs=[], steps=[])
    context = TranspilerContext(
        source=AnyUrl(Path("workflow.cwl").absolute().as_uri()),
        document={
            "first": first_workflow,
            "tool": command_line_tool,
            "second": second_workflow,
        },
        metadata=SoftwareApplication.model_construct(),
        resolver=RESOLVER,
    )

    processes = context.get_processes_by_type(WorkflowType)

    assert list(processes) == [first_workflow, second_workflow]


def test_transpiler_context_gets_processes_by_type_for_selected_ids() -> None:
    first_workflow = Workflow(id="first", inputs=[], outputs=[], steps=[])
    command_line_tool = CommandLineTool(id="tool", inputs=[], outputs=[])
    second_workflow = Workflow(id="second", inputs=[], outputs=[], steps=[])
    context = TranspilerContext(
        source=AnyUrl(Path("workflow.cwl").absolute().as_uri()),
        document={
            "first": first_workflow,
            "tool": command_line_tool,
            "second": second_workflow,
        },
        metadata=SoftwareApplication.model_construct(),
        resolver=RESOLVER,
    )

    processes = context.get_processes_by_type(
        Workflow, (process_id for process_id in ["second", "missing", "tool"])
    )

    assert list(processes) == [second_workflow]


def test_transpiler_context_get_processes_by_type_fails_if_empty() -> None:
    context = TranspilerContext(
        source=AnyUrl(Path("workflow.cwl").absolute().as_uri()),
        document={"tool": CommandLineTool(id="tool", inputs=[], outputs=[])},
        metadata=SoftwareApplication.model_construct(),
        resolver=RESOLVER,
    )

    with pytest.raises(PluginExecutionError, match=r"No .*Workflow.* found"):
        context.get_processes_by_type(Workflow)


def test_transpiler_context_get_processes_by_type_allows_empty_result() -> None:
    context = TranspilerContext(
        source=AnyUrl(Path("workflow.cwl").absolute().as_uri()),
        document={"tool": CommandLineTool(id="tool", inputs=[], outputs=[])},
        metadata=SoftwareApplication.model_construct(),
        resolver=RESOLVER,
    )

    processes = context.get_processes_by_type(Workflow, fail_if_empty=False)

    assert list(processes) == []


def test_transpiler_context_accepts_local_path_sources() -> None:
    source = AnyUrl(Path("workflow.cwl").absolute().as_uri())

    context = TranspilerContext(
        source=source,
        document={"asd": Workflow(inputs=[], outputs=[], steps=[])},
        metadata=SoftwareApplication.model_construct(),
        resolver=RESOLVER,
    )

    assert context.source == source


def test_transpiler_context_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TranspilerContext.model_validate(
            {
                "source": Path("workflow.cwl"),
                "document": Workflow(inputs=[], outputs=[], steps=[]),
                "metadata": SoftwareApplication.model_construct(),
                "resolver": RESOLVER,
                "unexpected": True,
            }
        )


@pytest.mark.parametrize(
    "source",
    [
        "http://example.com/workflow.cwl",
        "https://example.com/workflow.cwl",
        "oci://registry.example.com/workflows/example:latest",
        "file:///tmp/workflow.cwl",
        "s3://bucket/workflow.cwl",
    ],
)
def test_transpiler_context_accepts_url_sources(source: str) -> None:
    url = AnyUrl(source)

    context = TranspilerContext(
        source=url,
        document={"asd": Workflow(inputs=[], outputs=[], steps=[])},
        metadata=SoftwareApplication.model_construct(),
        resolver=RESOLVER,
    )

    assert context.source == url
