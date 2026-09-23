"""CCCIS 통합 실행: 로봇/RG2 + Main/Judgment + 선택적 HMI.
기본 terminal 모드는 HMI를 실행하지 않으며 START 전에는 검사 모션을 시작하지 않는다."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.substitutions import FindPackageShare


# 기능: 실물 드라이버와 시퀀스 실행을 묶고 선택한 운전 모드만 활성화한다.
def generate_launch_description():
    share = FindPackageShare('cable_pkg')
    return LaunchDescription([
        DeclareLaunchArgument('control_mode', default_value='terminal', choices=['terminal', 'hmi']),
        DeclareLaunchArgument('start_robot', default_value='true'),
        DeclareLaunchArgument('robot_host', default_value='192.168.1.100'),
        DeclareLaunchArgument('gripper_host', default_value='192.168.1.1'),
        DeclareLaunchArgument('robot_gui', default_value='false'),
        DeclareLaunchArgument('system_recipe', default_value=PathJoinSubstitution([
            share, 'config', 'system_recipe.json'])),
        DeclareLaunchArgument('recipe', default_value=PathJoinSubstitution([
            share, 'recipe', 'inspection', 'rcp_BMW_LWR_01.json'])),
        DeclareLaunchArgument('results_dir', default_value='results/inspection_sequence'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([share, 'launch', 'robot_bringup.launch.py'])),
            condition=IfCondition(LaunchConfiguration('start_robot')),
            launch_arguments={key: LaunchConfiguration(key) for key in
                              ('robot_host', 'gripper_host', 'robot_gui')}.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([share, 'launch', 'sequence_bringup.launch.py'])),
            launch_arguments={key: LaunchConfiguration(key) for key in
                              ('control_mode', 'system_recipe', 'recipe', 'results_dir')}.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('cable_hmi'), 'launch', 'hmi.launch.py'])),
            condition=IfCondition(PythonExpression(["'", LaunchConfiguration('control_mode'), "' == 'hmi'"])),
            launch_arguments={'mock': 'false'}.items(),
        ),
    ])
