import redis
import time
import csv
from datetime import datetime, timedelta
import asyncio
import ast
import numpy as np
from scipy.spatial.transform import Rotation as R
from instructor.moves.interpolation import interpolate_between_moves 
from instructor.utils import get_config, make_redis_client, read_log_array

cfg = get_config()
redis_client = make_redis_client()

DEFINE_MOVE_KEY = cfg["redis"]["keys"]["define_move"]
MOVE_LIST_KEY = cfg["redis"]["keys"]["move_list"]
EXECUTE_FLAG_KEY = cfg["redis"]["keys"]["execute_flag"]
MOVE_EXECUTED_KEY = cfg["redis"]["keys"]["move_executed"]

REALSENSE_PREFIX = cfg["redis"]["realsense_prefix"]

# rotate 90 counterclockwise around x
r1 = R.from_rotvec(np.pi/2 * np.array([1, 0, 0]))
# rotate 90 counterclockwise around z
r2 = R.from_rotvec(np.pi/2 * np.array([0, 0, 1]))
rot = r2 * r1

def read_data(file_path):
    data = []
    try:
        with open(file_path, 'r') as file:
            reader = csv.DictReader(file, delimiter='\t')
            for row in reader:
                data.append(row)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
    return data

def publish_to_redis(data, rate_hz=30):
    hand_coords = rot.apply(data[REALSENSE_PREFIX + "right_hand"])
    shoulder_coords = rot.apply(data[REALSENSE_PREFIX + "center_shoulders"])
    hip_coords = rot.apply(data[REALSENSE_PREFIX + "center_hips"])

    goal_coords = hand_coords - hip_coords

    torso_length = (shoulder_coords - hip_coords)[:,1:]
    torso_length = np.mean(np.linalg.norm(torso_length, axis=1))

    arm_length = 1.5 * torso_length
    goal_coords /= 2 * arm_length

    coords = np.clip(
        a=goal_coords,
        a_min=[0.49, -0.5, 0],
        a_max=[0.51, 0.5, 0.8],
    )

    for c in coords:
        redis_client.set("teleop::desired_pos", str(list(c)))
        time.sleep(1.0 / rate_hz)

def execute_move(move_id, interpolated=True):
    print("executing ", move_id)
    if interpolated:
        file_path = f"recordings/{move_id}_interpolated.txt"
    else: 
        file_path = f"recordings/{move_id}.txt"

    data = read_log_array(file_path)
    publish_to_redis(data, rate_hz=cfg["rate"])

def replay_moves():
    while True:
        execute_flag = redis_client.get(EXECUTE_FLAG_KEY)
        if execute_flag == "1": 
            print("Begining move execution")
            move_list = redis_client.lrange(MOVE_LIST_KEY, 0, -1)
            for i in range(len(move_list)):
                move_id = move_list[i]
                execute_move(move_id)
                redis_client.rpush(MOVE_EXECUTED_KEY, move_id)
                if i + 1 < len(move_list):
                    next_move = move_list[i + 1]
                    interpolate_between_moves(move_id, next_move)
                    execute_move(str(move_id) + "_to_" + str(next_move), False)
            print("Done with move execution!")
            redis_client.set(EXECUTE_FLAG_KEY, "0")
        
replay_moves()
