# CornerAim

面向 Windows 10/11 x64 的小窗练枪工具，用来练习无畏契约中的短距离微调。

## 下载

从 [GitHub Releases](https://github.com/SomthingLikeJms/CornerAim/releases/latest) 下载 `CornerAim.exe`，双击运行。

## 操作

- 左键点击训练区开始或继续。点射模式用左键，微调跟枪只需移动鼠标。
- 按 Alt 解锁鼠标并暂停。倒计时结束后自动解锁，点击「再练一局」继续训练。
- 拖动顶部移动窗口，拖动边缘缩放。缩放只调整可见范围，球径和鼠标位移比例以 360×240 的训练区为基准。
- 在「设置 → 参数」填写鼠标 DPI、游戏内灵敏度和每局秒数。eDPI 由鼠标 DPI 乘以游戏内灵敏度得出。

## 练习

| 模式 | 练习方式 |
| --- | --- |
| 单球微调 | 在准星附近短距离点射 |
| 爆头线微调 | 沿同一高度左右切换小靶 |
| 三球微调 | 三颗静止小靶，命中后在附近补位 |
| 视觉反应 | 等待随机亮球，见球即点 |
| 微调跟枪 | 小球在准星附近的小范围内随机转向，准星贴住球时每秒得 100 分 |

简单和困难的球径分别是中等的 120% 和 80%。三球各档共用球心间距和补位规则，参考了 [Aimlabs Micro 3 Sphere](https://aimlabs.com/articles/aimlabs/train-for-rainbow-six-siege-with-this-official-aim-basics-routine/)。

微调跟枪各档共用移动范围。简单慢速，中等提速，困难档的球会平滑加速和减速。贴住小球时球变蓝，结算显示得分、贴靶时长和贴靶率。贴靶率以实际练习时间计算。

「设置 → 参数」可开启摸鱼模式，选择纯透、浅底或深底。「统计」和「历史」可查看分模式、难度的成绩，包括命中率、耗时中位数和 P90。设置与成绩存放在 `%APPDATA%\CornerAim\corneraim.sqlite3`。

## 从源码运行

使用 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m corneraim
```

## 测试与打包

```powershell
.\.venv\Scripts\python.exe -m pip install pytest pyinstaller
.\.venv\Scripts\python.exe -m pytest -q
$caIcon = (Resolve-Path -LiteralPath 'corneraim/assets/corneraim.ico').Path
.\.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name CornerAim --paths . --icon $caIcon --add-data ($caIcon + ':corneraim/assets') --specpath .build --workpath .build/work corneraim/__main__.py
```

打包结果为 `dist/CornerAim.exe`。
