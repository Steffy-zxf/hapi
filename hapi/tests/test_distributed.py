# Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

import unittest
import os
import time
import six
import copy
from argparse import ArgumentParser, REMAINDER
import paddle
import paddle.fluid as fluid

from paddle.distributed.utils import *
import paddle.distributed.cloud_utils as cloud_utils


def get_cluster_from_args(selected_gpus):
    cluster_node_ips = '127.0.0.1'
    node_ip = '127.0.0.1'
    use_paddlecloud = False
    started_port = None
    node_ips = [x.strip() for x in cluster_node_ips.split(',')]

    node_rank = node_ips.index(node_ip)

    free_ports = None
    if not use_paddlecloud and len(node_ips) <= 1 and started_port is None:
        free_ports = find_free_ports(len(selected_gpus))
        if free_ports is not None:
            free_ports = list(free_ports)
    else:
        started_port = 6070

        free_ports = [
            x for x in range(started_port, started_port + len(selected_gpus))
        ]
    return get_cluster(node_ips, node_ip, free_ports, selected_gpus)


def get_gpus(selected_gpus):
    cuda_visible_devices = os.getenv("CUDA_VISIBLE_DEVICES")
    if cuda_visible_devices is None or cuda_visible_devices == "":
        selected_gpus = [x.strip() for x in selected_gpus.split(',')]
    else:
        cuda_visible_devices_list = cuda_visible_devices.split(',')
        for x in selected_gpus.split(','):
            assert x in cuda_visible_devices_list, "Can't find "\
            "your selected_gpus %s in CUDA_VISIBLE_DEVICES[%s]."\
            % (x, cuda_visible_devices)
        selected_gpus = [
            cuda_visible_devices_list.index(x.strip())
            for x in selected_gpus.split(',')
        ]
    return selected_gpus


def start_local_trainers(cluster,
                         pod,
                         training_script,
                         training_script_args,
                         log_dir=None):
    current_env = copy.copy(os.environ.copy())
    #paddle broadcast ncclUniqueId use socket, and
    #proxy maybe make trainers unreachable, so delete them.
    #if we set them to "", grpc will log error message "bad uri"
    #so just delete them.
    current_env.pop("http_proxy", None)
    current_env.pop("https_proxy", None)

    procs = []
    for idx, t in enumerate(pod.trainers):
        proc_env = {
            "FLAGS_selected_gpus": "%s" % ",".join([str(g) for g in t.gpus]),
            "PADDLE_TRAINER_ID": "%d" % t.rank,
            "PADDLE_CURRENT_ENDPOINT": "%s" % t.endpoint,
            "PADDLE_TRAINERS_NUM": "%d" % cluster.trainers_nranks(),
            "PADDLE_TRAINER_ENDPOINTS": ",".join(cluster.trainers_endpoints())
        }

        current_env.update(proc_env)

        print("trainer proc env:{}".format(current_env))

        cmd = "python -m coverage run --branch -p " + training_script

        print("start trainer proc:{} env:{}".format(cmd, proc_env))

        fn = None

        proc = subprocess.Popen(cmd.split(" "), env=current_env)

        tp = TrainerProc()
        tp.proc = proc
        tp.rank = t.rank
        tp.log_fn = fn
        tp.cmd = cmd

        procs.append(tp)

    return procs


class TestMultipleGpus(unittest.TestCase):
    def test_mnist_2gpu(self):
        if fluid.core.get_cuda_device_count() == 0:
            return

        selected_gpus = get_gpus('0,1')
        cluster = None
        pod = None

        cluster, pod = get_cluster_from_args(selected_gpus)

        procs = start_local_trainers(
            cluster,
            pod,
            training_script='dist_mnist.py',
            training_script_args=[])

        while True:
            alive = watch_local_trainers(procs, cluster.trainers_nranks())

            if not alive:
                print("Local procs complete, POD info:{}".format(pod))
                break
            time.sleep(3)


if __name__ == "__main__":
    unittest.main()
