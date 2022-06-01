"""A thin wrapper of ROS clients."""
import time
import logging
from typing import Optional, Sequence

import numpy as np
import rospy
import actionlib
from actionlib_msgs.msg import GoalStatus
import articulated.srv
import articulated.msg


logger = logging.getLogger(__name__)


class ImpedanceRegulation:
    def __init__(self, prefix="franka_"):
        self._c_get_T_ee = rospy.ServiceProxy(
            f"/{prefix}get_ee_transform", articulated.srv.GetEeTransform
        )
        self._c_regulate_ee = actionlib.SimpleActionClient(
            f"/{prefix}regulate_ee_transform", articulated.msg.RegulateEeTransformAction
        )
        self._c_config = rospy.ServiceProxy(
            f"/{prefix}set_regulate_ee_config", articulated.srv.SetRegulateEeConfig
        )
        self._status = "idle"

    def is_idle(self):
        state = self._c_regulate_ee.get_state()
        return (
            state == GoalStatus.SUCCEEDED
            or state == GoalStatus.PREEMPTED
            or state == GoalStatus.ABORTED
            or state == GoalStatus.LOST
        )

    def get_ee_transform(self):
        """Return the transform from origin to EE o_T_ee."""
        res = self._c_get_T_ee.call()
        return np.array(res.o_T_ee).reshape(4, 4)

    def set_ee(
        self,
        target_transform,
        stiffness=None,
        damping=None,
        ee_control_force_bound=50,
        ee_control_torque_bound=4,
    ):
        req = articulated.srv.SetRegulateEeConfigRequest()
        req.config.o_T_ee_desired = target_transform.flatten().tolist()
        self._fill_in_config(
            req.config,
            target_transform,
            stiffness,
            damping,
            ee_control_force_bound,
            ee_control_torque_bound,
        )
        self._c_config.call(req)

    def regulate_ee(
        self,
        target_transform,
        stiffness=None,
        damping=None,
        ee_control_force_bound=50,
        ee_control_torque_bound=4,
    ) -> None:
        """Return the transform from origin to EE o_T_ee."""
        if not self._c_regulate_ee.wait_for_server(rospy.Duration(3)):
            raise RuntimeError("Action server connection time out!")
        goal = articulated.msg.RegulateEeTransformGoal()
        self._fill_in_config(
            goal.config,
            target_transform,
            stiffness,
            damping,
            ee_control_force_bound,
            ee_control_torque_bound,
        )
        self._c_regulate_ee.send_goal(goal)
        state = self._c_regulate_ee.get_state()
        t0 = time.time()
        while state == GoalStatus.PENDING:
            state = self._c_regulate_ee.get_state()
            rospy.sleep(0.001)
            if time.time() - t0 > 10:
                self._c_regulate_ee.cancel_goal()
                raise RuntimeError("Timeout!")
        if state == GoalStatus.ABORTED:
            result = self._c_regulate_ee.get_result()
            raise RuntimeError("Goal aborted! %s" % result.status)

    @staticmethod
    def _fill_in_config(
        config,
        target_transform,
        stiffness: Optional[Sequence],
        damping: Optional[Sequence],
        ee_control_force_bound: float,
        ee_control_torque_bound: float,
    ):
        if stiffness is not None:
            assert len(stiffness) == 6, "Stiffness dimension does not match"
            stiffness = [150, 150, 150, 10, 10, 10]
        if damping is not None:
            assert len(stiffness) == 6, "Damping dimension does not match"
            damping = [30, 30, 30, 8, 8, 8]
        config.o_T_ee_desired = target_transform.flatten().tolist()
        config.stiffness = np.array(stiffness)
        config.damping = np.array(damping)
        config.ee_control_force_bound = ee_control_force_bound
        config.ee_control_torque_bound = ee_control_torque_bound

    def stop(self):
        if self.is_idle():
            logger.info("Robot is idle. No need to stop")
            return
        self._c_regulate_ee.cancel_goal()
        t0 = time.time()
        while not self.is_idle():
            time.sleep(0.001)
            if time.time() - t0 > 3:
                raise RuntimeError("Stop timeout!")


if __name__ == "__main__":
    rospy.init_node("franka_client_interface")
    robot = ImpedanceRegulation()
    T = robot.get_ee_transform()
    print(T)
    input("Enter to regulate at ee")
    robot.regulate_ee(T, ee_control_force_bound=5)
    t0 = time.time()
    while (not robot.is_idle()) and (time.time() - t0 < 10):
        time.sleep(0.5)
        if time.time() - t0 > 3:
            print("Command to stop")
            robot.stop()
