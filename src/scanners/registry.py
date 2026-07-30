from src.scanners.app_junk import AppJunkScanner
from src.scanners.base import Scanner
from src.scanners.browser_cache import BrowserCacheScanner
from src.scanners.dev_cache import DevCacheScanner
from src.scanners.duplicates import DuplicateFilesScanner
from src.scanners.empty_folders import EmptyFolderScanner
from src.scanners.extension_stats import ExtensionStatsScanner
from src.scanners.game_caches import GameCacheScanner
from src.scanners.gpu_caches import GpuCacheScanner
from src.scanners.installer_residue import InstallerResidueScanner
from src.scanners.large_files import LargeFilesScanner
from src.scanners.media_downloads import MediaDownloadsScanner
from src.scanners.office_comms import OfficeCommsScanner
from src.scanners.old_downloads import OldDownloadsScanner
from src.scanners.recycle_bin import RecycleBinScanner
from src.scanners.space_hogs import SpaceHogsScanner
from src.scanners.system_extras import SystemExtrasScanner
from src.scanners.temp_files import TempFilesScanner
from src.scanners.thumbnails import ThumbnailsScanner
from src.scanners.wechat import WeChatScanner
from src.scanners.windows_update import WindowsUpdateScanner


def all_scanners() -> list[Scanner]:
    return [
        TempFilesScanner(),
        WindowsUpdateScanner(),
        RecycleBinScanner(),
        ThumbnailsScanner(),
        BrowserCacheScanner(),
        SystemExtrasScanner(),
        GpuCacheScanner(),
        DevCacheScanner(),
        OfficeCommsScanner(),
        GameCacheScanner(),
        InstallerResidueScanner(),
        MediaDownloadsScanner(),
        OldDownloadsScanner(),
        LargeFilesScanner(),
        EmptyFolderScanner(),
        DuplicateFilesScanner(),
        ExtensionStatsScanner(),
        AppJunkScanner(),
        WeChatScanner(),
        SpaceHogsScanner(),
    ]


def scanner_category_order() -> list[str]:
    return [s.name for s in all_scanners()]
