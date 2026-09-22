"""HMI와 확정 시퀀스 Mock 노드를 함께 실행한다."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    """기존 검사 Mock을 끄고 Sequence Mock을 단독 status 발행자로 실행한다."""
    hmi_launch = Path(get_package_share_directory("cable_hmi")) / "launch/hmi.launch.py"
    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(hmi_launch)),
            launch_arguments={"mock": "false"}.items(),
        ),
        Node(
            package="cable_pkg",
            executable="sequence_test_node",
            output="screen",
        ),
    ])
