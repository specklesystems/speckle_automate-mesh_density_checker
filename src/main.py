from pydantic import Field
from speckle_automate import (
    AutomateBase,
    AutomationContext
)

from objects.objects import (
    attach_visual_markers,
    colorise_densities,
    create_health_objects,
    density_summary,
    transport_recolorized_commit
)
from src.utilities.reporting import generate_pdf, write_pdf_to_temp, generate_summary, safe_store_file_result
from src.utilities.utilities import filter_displayable_bases

class FunctionInputs(AutomateBase):
    """Definition of user inputs for this function.

    These fields define the parameters that users can adjust when triggering
    this function in the Speckle web application.
    """

    density_level: float = Field(
        title="Density Threshold",
        description=(
            "Set a density value as the threshold. objects with "
            "densities exceeding this value will be highlighted."
        ),
    )
    max_percentage_high_density_objects: float = Field(
        title="High Density Object Limit (%)",
        description=(
            "Specify the maximum percentage (0-1) of objects you're "
            "willing to allow above the set density threshold. "
            "For instance, a value of 0.1 means you'll tolerate up "
            "to 10% of the objects having a density above the threshold."
        ),
        ge=0.0,
        le=1.0,
    )


def automate_function(
    automate_context: AutomationContext, function_inputs: FunctionInputs
) -> None:
    """Analyzes Speckle data and provides visual markers and notifications.

    Fetches the specified version of the Speckle project, evaluates its objects
    based on their density, and reports results visually and as notifications.

    Args:
        automate_context (AutomationContext): Context for the current run,
            providing methods to fetch project data and send results.
        function_inputs (FunctionInputs): User-defined parameters guiding
            the analysis.
    """
    # Fetch the root object of the specified Speckle project version.
    version_root_object = automate_context.receive_version()

    # Filter out objects to keep only displayable ones with valid IDs.
    displayable_bases = filter_displayable_bases(version_root_object)

    if not displayable_bases:
        automate_context.mark_run_failed("No displayable mesh objects found.")
        return

    # Transform filtered objects to health objects for density analysis.
    health_objects = create_health_objects(displayable_bases)

    # Attach visual cues and notifications based on object densities.
    attach_visual_markers(
        automate_context, health_objects, function_inputs.density_level
    )

    colorise_densities(automate_context, health_objects)

    # Wrap up the analysis by marking the run either successful or failed.
    pass_rate_percentage = function_inputs.max_percentage_high_density_objects
    threshold = function_inputs.density_level
    data, all_densities, all_areas = density_summary(health_objects)

    print(dir(automate_context.automation_run_data))

    commit_details = {
        "stream_id": automate_context.automation_run_data.project_id,
        "commit_id": automate_context.automation_run_data.triggers[
            0
        ].payload.version_id,
        "server_url": automate_context.automation_run_data.speckle_server_url,
    }

    summary_data = generate_summary(
        threshold, pass_rate_percentage, health_objects, commit_details
    )

    report_data = {
        "table_data": summary_data["table"],
        "result": summary_data["values"]["result"],
    }

    high_density_count = summary_data["values"]["fail_count"]
    total_displayable_count = len(displayable_bases)

    report = generate_pdf(
        all_densities, [float(a) for a in all_areas], data, threshold, report_data
    )

    file_name = write_pdf_to_temp(report)

    print("------------------------------------------------")
    print(f"| {commit_details['server_url']} |")
    print("------------------------------------------------")

    safe_store_file_result(automate_context, file_name)

    # colorise the objects that pass/fail and send to a new model version
    transport_recolorized_commit(
        automate_context, health_objects, version_root_object
    )

    if summary_data["values"]["result"] == "Fail":
        automate_context.mark_run_failed(
            f"Too many high-density objects. Allowed: "
            f"{pass_rate_percentage * 100}%, Found: "
            f"{(high_density_count / total_displayable_count) * 100}%."
        )
    else:
        automate_context.mark_run_success(
            "Analysis complete. High-density objects within acceptable limits."
        )
