"""
HMI 실행 launch.

  가상 테스트 : ros2 launch cable_hmi hmi.launch.py
  실제 통합   : ros2 launch cable_hmi hmi.launch.py mock:=false
                (실제 검사 노드가 cable_hmi/interface.py 의 토픽을 제공해야 한다)
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """HMI 와 (선택) mock 검사 노드를 띄운다."""
    mock = LaunchConfiguration('mock')
    random_outcomes = LaunchConfiguration('random_outcomes')
    namespace = LaunchConfiguration('namespace')

    return LaunchDescription([
        DeclareLaunchArgument('mock', default_value='true',
                              description='가상 검사 노드를 함께 실행'),
        DeclareLaunchArgument('random_outcomes', default_value='false',
                              description='mock 의 Point 결과를 무작위로'),
        DeclareLaunchArgument('namespace', default_value='',
                              description='HMI/검사 노드 공통 namespace'),
        Node(
            package='cable_hmi', executable='mock_inspection_node', namespace=namespace,
            output='screen', condition=IfCondition(mock),
            parameters=[{'random_outcomes': ParameterValue(random_outcomes, value_type=bool)}],
        ),
        Node(package='cable_hmi', executable='hmi', namespace=namespace, output='screen'),
    ])
