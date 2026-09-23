"""Main Work와 비동기 Judgment를 실행하고 작업자 명령을 기다린다.
terminal 모드에서는 별도 터미널의 sequence_console로 운전한다."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.actions import OpaqueFunction
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


# 기능: 동일한 전체 시퀀스에 HMI 또는 터미널 명령 입력을 연결한다.
def _nodes(context):
    recipe_arguments = (["--recipe", LaunchConfiguration("recipe").perform(context)]
                        if LaunchConfiguration("control_mode").perform(context) == "terminal" else [])
    gripper_topic = ("/dsr01/gripper_joint_states"
                     if LaunchConfiguration("robot_mode").perform(context) == "virtual"
                     else "/onrobot_joint_states")
    main = Node(
        package='cable_inspection', executable='main_sequence', output='screen',
        arguments=[
            '--control-mode', LaunchConfiguration('control_mode'),
            '--robot-mode', LaunchConfiguration('robot_mode'),
            '--system-recipe', LaunchConfiguration('system_recipe'),
            '--results-dir', LaunchConfiguration('results_dir'),
        ] + recipe_arguments,
        sigterm_timeout='30', sigkill_timeout='10',
    )
    judgment = Node(package='cable_inspection', executable='inspection_judgment', output='screen')
    return [
        # 한쪽이 종료되면 짝 노드도 종료한다. Main은 종료 신호에서 STOP/Worker 정리를 수행한다.
        RegisterEventHandler(OnProcessExit(target_action=main, on_exit=[
            EmitEvent(event=Shutdown(reason='Main Work exited'))])),
        RegisterEventHandler(OnProcessExit(target_action=judgment, on_exit=[
            EmitEvent(event=Shutdown(reason='Inspection Judgment exited'))])),
        Node(package="cable_inspection", executable="robot_state_node", output="screen",
             parameters=[{"gripper_topic": gripper_topic}]),
        judgment,
        main,
    ]


def generate_launch_description():
    share = FindPackageShare("cable_inspection")
    return LaunchDescription([
        DeclareLaunchArgument('robot_mode', default_value='real', choices=['real', 'virtual']),
        DeclareLaunchArgument('control_mode', default_value='hmi', choices=['terminal', 'hmi']),
        DeclareLaunchArgument('system_recipe', default_value=PathJoinSubstitution([
            share, 'config', 'system_recipe.json'])),
        DeclareLaunchArgument('recipe', default_value=PathJoinSubstitution([
            share, 'recipe', 'inspection', 'rcp_BMW_LWR_01.json'])),
        DeclareLaunchArgument('results_dir', default_value='results/inspection_sequence'),
        OpaqueFunction(function=_nodes),
    ])
