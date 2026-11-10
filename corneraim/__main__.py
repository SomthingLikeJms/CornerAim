import argparse
import sys
from dataclasses import replace
from math import isfinite

from corneraim.profile import LocalStore
from corneraim.sens import CM360_EDPI


def positive_number(text: str) -> float:
    value = float(text)
    if not isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("请输入有限正数")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(prog="CornerAim", description="小窗微调与反应练习")
    sensitivity = parser.add_mutually_exclusive_group()
    sensitivity.add_argument("--edpi", type=positive_number, help="游戏 eDPI，默认 320")
    sensitivity.add_argument("--cm360", type=positive_number, help="游戏内转一圈所需的厘米数")
    mouse = parser.add_mutually_exclusive_group()
    mouse.add_argument("--dpi", type=positive_number, help="覆盖本次运行的鼠标 DPI")
    mouse.add_argument("--cpi", type=positive_number, help=argparse.SUPPRESS)
    parser.add_argument("--seconds", type=int, help="覆盖本次运行的训练时长，默认 30 秒")
    parser.add_argument("--windowed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not args.windowed and sys.platform != "win32":
        parser.error("角落小窗需要 Windows 10/11。")
    store = LocalStore.for_user()
    profile = store.load_profile()
    edpi = CM360_EDPI / args.cm360 if args.cm360 is not None else args.edpi
    dpi = args.dpi or args.cpi or profile.game_dpi
    if args.cpi is not None and edpi is None:
        edpi = profile.sensitivity.edpi
    try:
        profile = replace(
            profile,
            game_dpi=dpi,
            game_sens=profile.game_sens if edpi is None else edpi / dpi,
            seconds=profile.seconds if args.seconds is None else args.seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))

    from corneraim.app import Demo

    Demo(profile, store).run()


if __name__ == "__main__":
    main()
