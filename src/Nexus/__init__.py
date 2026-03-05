"""
Nexus Mods integration package.

Provides API access, NXM protocol handling, and download management
for the Nexus Mods ecosystem.
"""

from .nexus_api import NexusAPI, NexusModUpdateInfo
from .nxm_handler import NxmHandler, NxmLink, NxmIPC
from .nexus_download import NexusDownloader
from .nexus_meta import NexusModMeta, read_meta, write_meta, build_meta_from_download, scan_installed_mods
from .nexus_update_checker import check_for_updates, UpdateInfo
from .nexus_requirements import check_missing_requirements, check_requirements_from_gql, MissingRequirementInfo

__all__ = ["NexusAPI", "NexusModUpdateInfo", "NxmHandler", "NxmLink", "NxmIPC", "NexusDownloader",
           "NexusModMeta", "read_meta", "write_meta", "build_meta_from_download",
           "scan_installed_mods", "check_for_updates", "UpdateInfo",
           "check_missing_requirements", "check_requirements_from_gql", "MissingRequirementInfo"]
