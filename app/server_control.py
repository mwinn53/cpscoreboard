"""Shut the server down from the admin page: snapshot the data volume, then stop the instance.

Stopping (not terminating) is reversible: the instance, its Elastic IP and the
``/data`` volume are kept, and ``aws ec2 start-instances`` brings the site back.
The snapshot is a point-in-time copy of ``/data`` (database + season archive) taken
first, in case the volume is ever deleted. The instance role can only snapshot this
volume and stop this instance (infra/iam.tf).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class ServerControl:
    def __init__(self, region: str, instance_id: str, volume_id: str, name: str = "cpscoreboard"):
        self.region, self.instance_id, self.volume_id, self.name = region, instance_id, volume_id, name

    @property
    def available(self) -> bool:
        return bool(self.instance_id and self.volume_id)

    def snapshot(self) -> str:
        import boto3
        ec2 = boto3.client("ec2", region_name=self.region)
        snap = ec2.create_snapshot(
            VolumeId=self.volume_id, Description=f"{self.name}: final /data before shutdown",
            TagSpecifications=[{"ResourceType": "snapshot",
                                "Tags": [{"Key": "Name", "Value": f"{self.name}-final"},
                                         {"Key": "Project", "Value": self.name}]}])
        log.warning("Created snapshot %s of %s before shutdown", snap["SnapshotId"], self.volume_id)
        return snap["SnapshotId"]

    def stop(self) -> None:
        import boto3
        boto3.client("ec2", region_name=self.region).stop_instances(InstanceIds=[self.instance_id])
        log.warning("Stopping instance %s (admin request)", self.instance_id)
