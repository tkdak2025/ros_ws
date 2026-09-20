"""
실제 로봇 값 모니터링: HMI + robot_monitor_node (mock 없음, 읽기 전용).

먼저 다른 터미널에서 로봇 드라이버(sodreal 또는 sodvir)를 띄운 뒤 실행한다.
  ros2 launch cable_hmi hmi_monitor.launch.py
"""

from typing import List

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """HMI 와 로봇 모니터 노드를 띄운다."""
    return LaunchDescription([
        DeclareLaunchArgument('robot_ns', default_value='dsr01',
                              description='두산 드라이버 namespace'),
        # 드라이버 재시작으로 Tool/TCP 선택이 풀리면 이 이름으로 다시 설정한다.
        # 빈 문자열('')을 주면 설정은 건드리지 않고 HMI 에 경고만 띄운다.
        DeclareLaunchArgument('tool_name', default_value='ToolWeight'),
        DeclareLaunchArgument('tcp_name', default_value='GripperDA_v1'),
        # 2026-09-19 TP 에 등록된 ToolWeight 의 무게. TP 값을 바꾸면 여기도 같이 고칠 것.
        DeclareLaunchArgument('tool_weight_kg', default_value='1.47',
                              description='TP 에 등록된 tool_name 의 무게 (표시용, 0 이면 미표시)'),
        # HMI 'Home 이동' 버튼. 드라이버에 TP 의 사용자 홈 각도를 읽는 서비스가 없어서 여기에 적는다.
        # TP 의 사용자 홈과 같은 관절각으로 맞출 것. 끄려면 allow_home_move:=false
        DeclareLaunchArgument('allow_home_move', default_value='true'),
        DeclareLaunchArgument('home_joints', default_value='[0.0, 0.0, 90.0, 0.0, 90.0, 0.0]',
                              description='홈 관절각 6개 [deg]'),
        Node(package='cable_hmi', executable='robot_monitor_node', output='screen',
             parameters=[{
                 'robot_ns': LaunchConfiguration('robot_ns'),
                 'tool_name': ParameterValue(LaunchConfiguration('tool_name'), value_type=str),
                 'tcp_name': ParameterValue(LaunchConfiguration('tcp_name'), value_type=str),
                 'allow_home_move': ParameterValue(
                     LaunchConfiguration('allow_home_move'), value_type=bool),
                 'home_joints': ParameterValue(
                     LaunchConfiguration('home_joints'), value_type=List[float]),
                 'tool_weight_kg': ParameterValue(
                     LaunchConfiguration('tool_weight_kg'), value_type=float),
             }]),
        Node(package='cable_hmi', executable='hmi', output='screen'),
    ])
