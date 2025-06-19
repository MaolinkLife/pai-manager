# ==========================================================
# Module: initialize.py
# Purpose: Primary initialization of the LIM project before starting FastAPI.
# Responsible for preparing the environment: creating a config, generating user_id,
# checking directories and basic values.
#
# Used in: main.py
# Features:
# - Separates pre-startup checks from the API startup logic
# - Can be called separately as a setup procedure
# =========================================================
import uuid

from services import config_service
from services import database_service
from services import preset_service

from services.logger_service import initialize_log_files, log_audit, log_audit_entry, AuditStatus

from utils.structure_utils import get_label_from_file

def run_startup_checks():
    """
    The main method for initializing LIM.
    Runs when main.py starts, before the application starts.
    """

    print("Starting LIM initialization...")
    log_audit_entry(
        event_type="startup_begin", 
        msg=f"{get_label_from_file(__file__)} Starting LIM initialization", 
        status=AuditStatus.SUCCESS
    )

    # Checking for availability and creating a config
    config_service.ensure_config_exists()
    preset_service.ensure_presets_exist()
    
    initialize_log_files()

    # Generate user_id if it is missing
    if not config_service.get_config_value("user_id"):
        user_id = str(uuid.uuid4())
        config_service.set_config_value("user_id", user_id)
        log_audit("user_id_generated", {"user_id": user_id})

    # Create a database
    database_service.create_database()


    # Additional checks may be added here in the future:
    # - presence of directories
    # - presence of char_name
    # - config.json structure

    print("Initialization completed successfully.")
    log_audit_entry(
        event_type="startup_complete", 
        msg=f"{get_label_from_file(__file__)} Initialization complete", 
        status=AuditStatus.SUCCESS
    )
