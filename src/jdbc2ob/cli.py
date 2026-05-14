import argparse
from pathlib import Path

from .proxy import run_capture


def build_parser():
    parser = argparse.ArgumentParser(
        description="jdbc connection -> jdbc2pcap(listen_host:listen_port) ->FakeMySQL(rhost:rport)"
    )

    # 本工具监听的本地地址。
    parser.add_argument(
        "--lhost",
        default="127.0.0.1",
        help="proxy listen_host, default 127.0.0.1",
    )

    # 本工具监听的本地端口。
    parser.add_argument(
        "--lport",
        type=int,
        default=3307,
        help="proxy listen port, default 3307",
    )

    # FakeMySQL 的主机地址。
    parser.add_argument(
        "--rhost",
        default="127.0.0.1",
        help="FakeMySQL host, default 127.0.0.1",
    )

    # FakeMySQL 的监听端口。
    parser.add_argument(
        "--rport",
        type=int,
        default=3306,
        help="FakeMySQL port, default 3306",
    )

    # 是否显式生成 namedpipe_payload.bin。
    # 当前逻辑中即使不传 --ob，也默认生成该文件；保留该参数用于明确表达输出意图。


    # 输出目录。
    parser.add_argument(
        "--od",
        default="output",
        help="output directory(default ./output)",
    )

    # socket 接收缓冲区大小。
    # 一般保持默认即可；如果上游 FakeMySQL 单次返回很大的数据块，可以适当调大。
    parser.add_argument(
        "--size",
        type=int,
        default=65536,
        help="socket recv buffer size",
    )

    # 会话空闲超时时间。
    # 当 JDBC 与 FakeMySQL 双方在指定时间内都没有新数据时，关闭当前 session 并保存结果。
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="close current session after N seconds idle, default 2",
    )

    # 是否持续监听。
    # 默认处理一个 JDBC 连接后退出；开启后会在当前 session 结束后继续等待下一次连接。
    parser.add_argument(
        "--keep-listening",
        action="store_true",
        help="continue listening after a session ends",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    run_capture(
        listen_host=args.lhost,
        listen_port=args.lport,
        upstream_host=args.rhost,
        upstream_port=args.rport,
        out_dir=Path(args.od),
        buffer_size=args.size,
        idle_timeout=args.timeout,
        keep_listening=args.keep_listening,
    )