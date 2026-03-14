#!/usr/bin/env python3
# evaluation.py — modified for 3-node Chameleon Cloud setup (autothrottle-1/2/3)
# Original paper used 5 Azure VMs; services from nodes 4 and 5 are redistributed
# to autothrottle-2 and autothrottle-3. Only social_network() is run.
# hotel_reservation() and train_ticket() are commented out (require nodes 4 and 5).

import resource
import signal
import sys

from utils import *

resource.setrlimit(resource.RLIMIT_NOFILE, (65535, 1048576))
signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))


# Every time a benchmark finishes, this function will be called.
# You can use this function to send a notification to your phone or do some other stuff.
def send_notification(message):
    try:
        pass
        # import os
        # os.system(f'timeout 60 curl ...')
        # import requests
        # requests.post(
        #     '...',
        #     json=...,
        #     timeout=60,
        # )
    except Exception:
        traceback.print_exc()


def application(name, slo, nodes, target1components, deploy, teardown, traces_and_targets, trace_multiplier, aggregate_samples):
    locustfile = f'{name}/locustfile.py'
    url = 'http://localhost:30001'
    namespace = name
    components = sorted(sum(nodes.values(), []))
    locust_workers = 8
    warmup_minutes = 3  # see section A.7 in the paper
    warmup_seconds = warmup_minutes * 60
    initial_limit = 32
    tower_targets = [0.0, 0.02, 0.04, 0.06, 0.1, 0.15, 0.2, 0.25, 0.3]  # see section 4 in the paper
    samples = []

    # all our locustfiles are designed to read each second's RPS from rps.txt
    trace = load_trace('traces/diurnal-2.txt')
    trace = [round(i * trace_multiplier) for i in trace]
    warmup = []
    for i in range(warmup_seconds):
        rps = round(trace[0] * 1.1 ** ((i - warmup_seconds) / 5))  # x1.1 every 5 seconds, see section A.7 in the paper
        if rps < 1:
            rps = 1
        warmup.append(rps)
    trace = warmup + trace
    dump_trace(trace, 'rps.txt')

    # see section A.7 in the paper for the warmup process
    for i in range(6):
        path = f'data/{name}/autothrottle-warmup/a{i + 1}'
        if benchmark(
            output_dir=path,
            namespace=namespace,
            locustfile=locustfile,
            url=url,
            nodes=nodes,
            deploy=deploy,
            teardown=teardown,
            scalers={i: {'type': 'captain', 'params': (0.0, initial_limit)} for i in components},
            tower=ExploreTower(
                scaler='captain',
                targets=tower_targets,
                target1components=target1components,
                samples=[],
                warmup=warmup_minutes,
            ),
            locust_workers=locust_workers,
        ):
            allocation = TimeSeries.zip_with(lambda *args: sum(args), *[v for k, v in load_cpu_limit(path).items()]) \
                .downsample_time_weighted_average(60).slice(warmup_seconds + 30, float('inf')).average()
            request_latency = load_request_latency(path).slice(warmup_seconds, float('inf'))
            p99_latency = request_latency.percentage(99)
            average_rps = len(request_latency) / 3600
            log = {
                'time': datetime.datetime.utcnow().isoformat() + 'Z',
                'path': path,
                'application': name,
                'trace': 'diurnal-2',
                'scaler': 'autothrottle',
                'warmup': f'a{i + 1}',
                'allocation': allocation,
                'p99_latency': p99_latency,
                'average_rps': average_rps,
            }
            with open('log.json', 'a') as f:
                f.write(json.dumps(log) + '\n')
            send_notification(f'{name} warmup {i + 1} / 12 finished')
        samples += load_samples(path)
    for i in range(6):
        path = f'data/{name}/autothrottle-warmup/b{i + 1}'
        if benchmark(
            output_dir=path,
            namespace=namespace,
            locustfile=locustfile,
            url=url,
            nodes=nodes,
            deploy=deploy,
            teardown=teardown,
            scalers={i: {'type': 'captain', 'params': (0.0, initial_limit)} for i in components},
            tower=VwTower(
                scaler='captain',
                targets=tower_targets,
                target1components=target1components,
                slo=slo,
                samples=samples,
                explore=0.5,
                drop_samples=warmup_minutes,
                aggregate_samples=aggregate_samples,
            ),
            locust_workers=locust_workers,
        ):
            allocation = TimeSeries.zip_with(lambda *args: sum(args), *[v for k, v in load_cpu_limit(path).items()]) \
                .downsample_time_weighted_average(60).slice(warmup_seconds + 30, float('inf')).average()
            request_latency = load_request_latency(path).slice(warmup_seconds, float('inf'))
            p99_latency = request_latency.percentage(99)
            average_rps = len(request_latency) / 3600
            log = {
                'time': datetime.datetime.utcnow().isoformat() + 'Z',
                'path': path,
                'application': name,
                'trace': 'diurnal-2',
                'scaler': 'autothrottle',
                'warmup': f'b{i + 1}',
                'allocation': allocation,
                'p99_latency': p99_latency,
                'average_rps': average_rps,
            }
            with open('log.json', 'a') as f:
                f.write(json.dumps(log) + '\n')
            send_notification(f'{name} warmup {i + 7} / 12 finished')
        samples += load_samples(path)[warmup_minutes:]

    for trace_name, scaler_targets in traces_and_targets.items():
        # all our locustfiles are designed to read each second's RPS from rps.txt
        if isinstance(trace_name, str):
            workload_name = trace_name
            trace = load_trace(f'traces/{trace_name}.txt')
            trace = [round(i * trace_multiplier) for i in trace]
        elif isinstance(trace_name, int):
            workload_name = 'constant'
            trace = [trace_name] * 3600
        else:
            raise ValueError
        warmup = []
        for i in range(warmup_seconds):
            rps = round(trace[0] * 1.1 ** ((i - warmup_seconds) / 5))  # x1.1 every 5 seconds, see section A.7 in the paper
            if rps < 1:
                rps = 1
            warmup.append(rps)
        trace = warmup + trace
        dump_trace(trace, 'rps.txt')

        path = f'data/{name}/{trace_name}/autothrottle'
        if benchmark(
            output_dir=path,
            namespace=namespace,
            locustfile=locustfile,
            url=url,
            nodes=nodes,
            deploy=deploy,
            teardown=teardown,
            scalers={i: {'type': 'captain', 'params': (0.0, initial_limit)} for i in components},
            tower=VwTower(
                scaler='captain',
                targets=tower_targets,
                target1components=target1components,
                slo=slo,
                samples=samples,
                # this is only for evaluation, see section A.7 in the paper
                # normally, 0.1 is a good value and no warmup process is needed
                explore=0.0,
                drop_samples=warmup_minutes,
                aggregate_samples=aggregate_samples,
            ),
            locust_workers=locust_workers,
        ):
            allocation = TimeSeries.zip_with(lambda *args: sum(args), *[v for k, v in load_cpu_limit(path).items()]) \
                .downsample_time_weighted_average(60).slice(warmup_seconds + 30, float('inf')).average()
            request_latency = load_request_latency(path).slice(warmup_seconds, float('inf'))
            p99_latency = request_latency.percentage(99)
            average_rps = len(request_latency) / 3600
            log = {
                'time': datetime.datetime.utcnow().isoformat() + 'Z',
                'path': path,
                'application': name,
                'trace': trace_name,
                'scaler': 'autothrottle',
                'allocation': allocation,
                'p99_latency': p99_latency,
                'average_rps': average_rps,
            }
            with open('log.json', 'a') as f:
                f.write(json.dumps(log) + '\n')
            if p99_latency <= slo:
                with open('result.csv', 'a') as f:
                    f.write(f'{name},{workload_name},autothrottle,{allocation:.2f}\n')
                send_notification(f'{name} {workload_name} autothrottle result: {allocation:.2f}')
            else:
                detail = f'SLO not met. P99 latency = {p99_latency*1e3:.0f} ms. SLO = {slo*1e3:.0f} ms. Delete this path to run again: {path}'
                with open('result.csv', 'a') as f:
                    f.write(f'{name},{workload_name},autothrottle,N/A\n')
                    f.write(f'# ^ {detail}\n')
                send_notification(f'{name} {workload_name} autothrottle result: N/A. {detail}')

        for scaler, targets in scaler_targets.items():
            for target in targets:
                path = f'data/{name}/{trace_name}/{scaler}/{target}'
                if benchmark(
                    output_dir=path,
                    namespace=namespace,
                    locustfile=locustfile,
                    url=url,
                    nodes=nodes,
                    deploy=deploy,
                    teardown=teardown,
                    scalers={i: {'type': scaler, 'params': (target, initial_limit)} for i in components},
                    tower=DummyTower(),
                    locust_workers=locust_workers,
                ):
                    allocation = TimeSeries.zip_with(lambda *args: sum(args), *[v for k, v in load_cpu_limit(path).items()]) \
                        .downsample_time_weighted_average(60).slice(warmup_seconds + 30, float('inf')).average()
                    request_latency = load_request_latency(path).slice(warmup_seconds, float('inf'))
                    p99_latency = request_latency.percentage(99)
                    average_rps = len(request_latency) / 3600
                    log = {
                        'time': datetime.datetime.utcnow().isoformat() + 'Z',
                        'path': path,
                        'application': name,
                        'trace': trace_name,
                        'scaler': scaler,
                        'target': target,
                        'allocation': allocation,
                        'p99_latency': p99_latency,
                        'average_rps': average_rps,
                    }
                    with open('log.json', 'a') as f:
                        f.write(json.dumps(log) + '\n')
                    if p99_latency <= slo:
                        with open('result.csv', 'a') as f:
                            f.write(f'{name},{workload_name},{scaler},{allocation:.2f}\n')
                        send_notification(f'{name} {workload_name} {scaler} result: {allocation:.2f}')
                    else:
                        detail = f'SLO not met. P99 latency = {p99_latency*1e3:.0f} ms. SLO = {slo*1e3:.0f} ms. Delete this path to run again: {path}'
                        with open('result.csv', 'a') as f:
                            f.write(f'{name},{workload_name},{scaler},N/A\n')
                            f.write(f'# ^ {detail}\n')
                        send_notification(f'{name} {workload_name} {scaler} result: N/A. {detail}')


def social_network():
    def deploy():
        # 3-node version uses 1-3nodes.json and 2-3nodes.json
        kubectl_apply(['social-network/1-3nodes.json', 'social-network/2-3nodes.json'], 'social-network', 31)
        time.sleep(180)
        # populate the database, see section A.7 in the paper
        subprocess.run([sys.executable, 'social-network/src/scripts/setup_social_graph_init_data_sync.py'], check=True)

    def teardown():
        kubectl_delete(['social-network/1-3nodes.json', 'social-network/2-3nodes.json'], 'social-network')

    application(
        name='social-network',
        slo=0.2,  # see section 5.1 in the paper
        nodes={
            # autothrottle-2: original nodes 2 + nginx-thrift from node 5
            'autothrottle-2': [
                'home-timeline-service',
                'media-filter-service-1',
                'nginx-thrift',           # originally on autothrottle-5
            ],
            # autothrottle-3: original nodes 3 + all of node 4
            'autothrottle-3': [
                'media-filter-service-2',
                'post-storage-service',
                'compose-post-redis',        # originally on autothrottle-4
                'compose-post-service',
                'home-timeline-redis',
                'media-filter-service-3',
                'media-service',
                'post-storage-memcached',
                'post-storage-mongodb',
                'social-graph-mongodb',
                'social-graph-redis',
                'social-graph-service',
                'text-filter-service',
                'text-service',
                'unique-id-service',
                'url-shorten-service',
                'user-memcached',
                'user-mention-service',
                'user-mongodb',
                'user-service',
                'user-timeline-mongodb',
                'user-timeline-redis',
                'user-timeline-service',
                'write-home-timeline-rabbitmq',
                'write-home-timeline-service',
                'write-user-timeline-rabbitmq',
                'write-user-timeline-service',
            ],
        },
        target1components={
            'media-filter-service-1',
            'media-filter-service-2',
            'media-filter-service-3',
        },
        deploy=deploy,
        teardown=teardown,
        traces_and_targets={  # see section A.6 in the paper
            'diurnal': {
                'k8s-cpu': [0.5],
                'k8s-cpu-fast': [0.5],
            },
            500: {
                'k8s-cpu': [0.5],
                'k8s-cpu-fast': [0.6],
            },
            'noisy': {
                'k8s-cpu': [0.5],
                'k8s-cpu-fast': [0.4],
            },
            'bursty': {
                'k8s-cpu': [0.5],
                'k8s-cpu-fast': [0.4],
            },
        },
        trace_multiplier=1.5,
        aggregate_samples=20,
    )


# hotel_reservation() and train_ticket() are not run in this 3-node setup
# as they require autothrottle-4 and autothrottle-5

social_network()