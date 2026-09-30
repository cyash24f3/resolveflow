"""Fence checkpoint publications with the same current job ownership as business writes."""

from langgraph.checkpoint.base import BaseCheckpointSaver

from resolveflow.jobs.queue import fence


class FencedSaver(BaseCheckpointSaver):
    def __init__(self, inner, factory, run_id, owner):
        super().__init__(serde=inner.serde)
        self.inner, self.factory, self.run_id, self.owner = inner, factory, run_id, owner

    @property
    def config_specs(self):
        return self.inner.config_specs

    def get_tuple(self, config):
        return self.inner.get_tuple(config)

    def list(self, config, **kwargs):
        yield from self.inner.list(config, **kwargs)

    def put(self, config, checkpoint, metadata, new_versions):
        with self.factory.begin() as s:
            fence(s, self.run_id, self.owner)
            return self.inner.put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        with self.factory.begin() as s:
            fence(s, self.run_id, self.owner)
            self.inner.put_writes(config, writes, task_id, task_path)

    def get_next_version(self, current, channel):
        return self.inner.get_next_version(current, channel)
