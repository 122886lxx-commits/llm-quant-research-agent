from .models import Pipeline


class PipelineValidator:
    def validate(self, pipeline: Pipeline) -> None:
        self._ensure_steps(pipeline)
        self._ensure_unique_ids(pipeline)
        self._ensure_all_edges_point_to_known_steps(pipeline)

    def _ensure_steps(self, pipeline: Pipeline) -> None:
        if not pipeline.steps:
            raise ValueError("Pipeline requires at least one step")

    def _ensure_unique_ids(self, pipeline: Pipeline) -> None:
        step_ids = [step.id for step in pipeline.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Duplicate step ids")

    def _ensure_all_edges_point_to_known_steps(self, pipeline: Pipeline) -> None:
        known_ids = {step.id for step in pipeline.steps}
        for step in pipeline.steps:
            for target in step.next or []:
                if target not in known_ids:
                    raise ValueError("Unknown target '{0}' referenced by '{1}'".format(target, step.id))

