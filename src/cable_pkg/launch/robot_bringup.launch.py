"""실물 M0609와 RG2 드라이버를 실행한다. 검사 모션은 시작하지 않는다."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


# 기능: 고정된 dsr01/M0609 구성으로 로봇과 RG2를 연결한다.
def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('robot_host', default_value='192.168.1.100'),
        DeclareLaunchArgument('gripper_host', default_value='192.168.1.1'),
        DeclareLaunchArgument('robot_gui', default_value='false'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('dsr_bringup2'), 'launch', 'dsr_bringup2_rviz.launch.py'])),
            launch_arguments={
                'name': 'dsr01', 'model': 'm0609', 'mode': 'real',
                'host': LaunchConfiguration('robot_host'), 'port': '12345',
                'gui': LaunchConfiguration('robot_gui'),
            }.items(),
        ),
        Node(
            package='onrobot_rg_control', executable='OnRobotRGControllerServer',
            namespace='dsr01', name='OnRobotRGControllerServer',
            output='screen',
            parameters=[{
                '/onrobot/control': 'modbus', '/onrobot/ip': LaunchConfiguration('gripper_host'),
                '/onrobot/port': 502, '/onrobot/changer_addr': 65,
                '/onrobot/gripper': 'rg2', '/onrobot/offset': 5,
            }],
            remappings=[('/joint_states', '/onrobot_joint_states')],
        ),
    ])
