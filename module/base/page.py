# Adapted from AzurPilot/module/ui/page.py (GPL-3.0).
# Changes: standalone imports and explicit page names for the WarshipR graph.
import traceback

class Page:
    """UI 页面定义类。

    每个 Page 实例代表游戏中的一个可导航页面。
    通过 `link()` 方法建立页面间的导航关系，形成有向图。
    `init_connection()` 使用 BFS 算法预计算从目标页面到所有源页面的最短路径。

    Attributes:
        all_pages (dict[str, Page]): 全局页面注册表，键为页面变量名。
        check_button (Button): 页面标识按钮，用于检测当前是否在此页面。
        links (dict[Page, Button]): 到达其他页面的链接，键为目标页面，值为点击按钮。
        name (str): 页面变量名，如 'page_main'、'page_campaign'。
        parent (Page | None): 在 A* 寻路中指向目标方向的父页面。
    """
    # 键: str, 页面名称如 "page_main"
    # 值: Page, 页面实例
    all_pages = {}

    @classmethod
    def clear_connection(cls):
        """清除所有页面的父级导航连接。"""
        for page in cls.all_pages.values():
            page.parent = None

    @classmethod
    def init_connection(cls, destination):
        """初始化页面间的 A* 寻路连接。

        Args:
            destination (Page): 目标页面。
        """
        cls.clear_connection()

        visited = [destination]
        visited = set(visited)
        while 1:
            new = visited.copy()
            for page in visited:
                for link in cls.iter_pages():
                    if link in visited:
                        continue
                    if page in link.links:
                        link.parent = page
                        new.add(link)
            if len(new) == len(visited):
                break
            visited = new

    @classmethod
    def iter_pages(cls):
        """遍历所有已注册的页面。

        Returns:
            dict_values: 所有 Page 实例的集合视图。
        """
        return cls.all_pages.values()

    @classmethod
    def iter_check_buttons(cls):
        """生成所有页面的标识检查按钮。

        Yields:
            Button: 各页面的 check_button。
        """
        for page in cls.all_pages.values():
            yield page.check_button

    def __init__(self, check_button, name=None):
        """初始化 UI 页面实例。

        Args:
            check_button (Button | None): 用于检测当前是否在该页面的标识按钮。
        """
        self.check_button = check_button
        self.links = {}
        (filename, line_number, function_name, text) = traceback.extract_stack()[-2]
        self.name = name or text[:text.find('=')].strip()
        self.parent = None
        Page.all_pages[self.name] = self

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name

    def link(self, button, destination):
        """建立从当前页面到目标页面的单向导航链接。

        Args:
            button (Button): 点击以跳转到目标页面的按钮。
            destination (Page): 目标页面实例。
        """
        self.links[destination] = button
