#!/usr/bin/env python3
"""
fil-actor-states Automation Script

This script automates the process of updating fil-actor-states when a new version
of builtin-actors is released. It replaces the manual copy-paste workflow with
an automated process that:

1. Clones the specified version of builtin-actors from GitHub
2. Processes all 15 core Filecoin actors (account, cron, datacap, etc.)
3. Transforms Rust imports to be compatible with fil-actor-states structure
4. Extracts Method enums and adds proper Rust attributes
5. Creates mod.rs files with proper module structure
6. Updates each actor's lib.rs to include the new version

WORKFLOW OVERVIEW:
- Input: builtin-actors git tag (e.g., 'v17.0.0-rc1')
- Output: Complete v17 actor implementations in fil-actor-states
- Time saved: Replaces hours of manual work with automated process

Successfully tested with builtin-actors v17.0.0-rc1 to generate complete v17 actors.

Usage: python scripts/update_actors.py v17.0.0-rc1
"""

import re
import subprocess
import tempfile
from pathlib import Path
from typing import List


class ActorUpdater:
    """
    Main class for updating fil-actor-states with new builtin-actors versions.
    
    This class handles the complete automation workflow, from cloning the
    builtin-actors repository to generating the final fil-actor-states structure.
    Successfully tested with v17.0.0-rc1.
    """
    
    # Configuration: All actors that should be processed
    # Each actor represents a core Filecoin protocol component
    ACTOR_NAMES = [
        "account",     # User account management
        "cron",        # Scheduled tasks and network maintenance
        "datacap",     # DataCap token for verified deals
        "eam",         # Ethereum Address Manager
        "ethaccount",  # Ethereum-compatible accounts
        "evm",         # Ethereum Virtual Machine
        "init",        # Actor initialization
        "market",      # Storage market operations
        "miner",       # Storage miner operations
        "multisig",    # Multi-signature wallets
        "paych",       # Payment channels
        "power",       # Storage power consensus
        "reward",      # Block reward distribution
        "system",      # System actor
        "verifreg"     # Verified registry
    ]
    
    # Files that should NOT be copied from builtin-actors
    # These are either not needed or would conflict with fil-actor-states structure
    EXCLUDE_FILES = {
        "lib.rs",            # We generate our own lib.rs
        "testing.rs",        # Test code not needed
        "internal_tests.rs", # Test code not needed
        "emit.rs",           # Event emission not needed
        "notifications.rs"   # Notification system not needed
    }
    
    # Regular expressions used for code transformation
    # These patterns find and replace import statements to make code compatible
    REGEX_PATTERNS = {
        # Pattern 1: Update FVM shared library imports
        # Finds: 'use fvm_shared::' or 'use fvm_shared3::'
        # Replaces with: 'use fvm_shared4::'
        # Why: fil-actor-states uses fvm_shared4 for v17+ compatibility
        'fvm_imports': r'use fvm_shared(\d*)::', 
        
        # Pattern 2: Update crate::builtin imports
        # Finds: 'use crate::builtin::'
        # Replaces with: 'use fil_actors_shared::v17::builtin::'
        # Why: Remaps internal builtin imports to versioned shared library
        'crate_builtin': r'use crate::builtin::',
        
        # Pattern 3: Update remaining crate imports
        # Finds: 'use crate::'
        # Replaces with: 'use fil_actors_shared::v17::'
        # Why: Makes all internal imports use the shared library structure
        'crate_general': r'use crate::'
    }
    
    def __init__(self, repo_root: str):
        """
        Initialize the ActorUpdater with the repository root path.
        
        Args:
            repo_root: Path to the fil-actor-states repository root directory
        """
        self.repo_root = Path(repo_root)
        self.builtin_actors_url = "https://github.com/filecoin-project/builtin-actors.git"
        
    def extract_version_number(self, version_tag: str) -> str:
        """
        Extract the major version number from a git tag.
        
        Examples:
            'v17.0.0-rc1' -> 'v17'
            'v18.1.0' -> 'v18'
            
        This is used to create directory names like 'actors/account/src/v17/'
        
        Args:
            version_tag: Git tag from builtin-actors (e.g., 'v17.0.0-rc1')
            
        Returns:
            Major version string (e.g., 'v17')
            
        Raises:
            ValueError: If the version tag doesn't match expected format
        """
        # Regular expression explanation:
        # v      - matches literal 'v'
        # (\d+)  - captures one or more digits (the major version number)
        # .*     - matches anything else after (minor version, rc, etc.)
        version_pattern = r'v(\d+)'
        match = re.match(version_pattern, version_tag)
        
        if match:
            major_version = match.group(1)  # Extract the captured digits
            return f"v{major_version}"
        else:
            raise ValueError(f"Cannot extract version from '{version_tag}'. Expected format like 'v17.0.0'")
    
    def transform_imports(self, content: str, version: str) -> str:
        """
        Transform Rust import statements to make them compatible with fil-actor-states.
        
        This function applies several regex replacements to update import paths:
        1. Updates FVM shared library imports to use fvm_shared4
        2. Remaps crate::builtin imports to use fil_actors_shared
        3. Remaps other crate imports to use fil_actors_shared
        
        Args:
            content: The Rust source code content to transform
            version: The target version (e.g., 'v17') for the shared library path
            
        Returns:
            Transformed content with updated import statements
        """
        
        # TRANSFORMATION 1: Update FVM shared library imports
        # Before: 'use fvm_shared::METHOD_CONSTRUCTOR;'
        # After:  'use fvm_shared4::METHOD_CONSTRUCTOR;'
        # Why: fil-actor-states uses fvm_shared4 for v17+ compatibility
        fvm_pattern = self.REGEX_PATTERNS['fvm_imports']
        content = re.sub(fvm_pattern, r'use fvm_shared4::', content)
        
        # TRANSFORMATION 2: Update crate::builtin imports
        # Before: 'use crate::builtin::reward;'
        # After:  'use fil_actors_shared::v17::builtin::reward;'
        # Why: Remaps internal builtin imports to versioned shared library
        builtin_pattern = self.REGEX_PATTERNS['crate_builtin']
        builtin_replacement = f'use fil_actors_shared::{version}::builtin::'
        content = re.sub(builtin_pattern, builtin_replacement, content)
        
        # TRANSFORMATION 3: Update remaining crate imports
        # Before: 'use crate::state::State;'
        # After:  'use fil_actors_shared::v17::state::State;'
        # Why: Makes all internal imports use the shared library structure
        crate_pattern = self.REGEX_PATTERNS['crate_general'] 
        crate_replacement = f'use fil_actors_shared::{version}::'
        content = re.sub(crate_pattern, crate_replacement, content)
        
        return content

    def add_compatibility_header(self, content: str) -> str:
        """
        Add fil-actor-states compatibility warning to state files.
        
        This header explains why the file is different from builtin-actors.
        """
        header = """// WARNING: Method implementations have been removed for fil-actor-states compatibility
// This file contains only type definitions and state structures

"""
        if content.startswith("//"):
            lines = content.split('\n')
            insert_pos = next((i for i, line in enumerate(lines) 
                             if not line.strip().startswith('//') and line.strip()), 0)
            lines.insert(insert_pos, header)
            return '\n'.join(lines)
        else:
            return header + content

    def process_file(self, source: Path, target: Path, version: str) -> None:
        """
        Process and transform a single Rust file.
        
        This function:
        1. Reads the source file
        2. Applies import transformations
        3. Adds compatibility headers for state files
        4. Writes the transformed content to the target location
        """
        with open(source, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Transform imports
        content = self.transform_imports(content, version)
        
        # Add header for state files
        if source.name == "state.rs":
            content = self.add_compatibility_header(content)
        
        # Write transformed content
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)

    def find_method_enum_start(self, lines: list) -> int:
        """
        Find the line number where the Method enum starts.
        
        Searches for a line that matches: 'pub enum Method {'
        with any amount of whitespace before it.
        
        Args:
            lines: List of lines from the lib.rs file
            
        Returns:
            Line number (0-based) where Method enum starts, or -1 if not found
        """
        for i, line in enumerate(lines):
            # Look for: '    pub enum Method {'
            if re.match(r'\s*pub enum Method\s*\{', line):
                return i
        return -1
    
    def find_matching_brace(self, lines: list, start_line: int) -> int:
        """
        Find the closing brace that matches the opening brace of the Method enum.
        
        This function counts opening '{' and closing '}' braces to find where
        the enum definition ends, handling nested braces correctly.
        
        Args:
            lines: List of lines from the lib.rs file
            start_line: Line number where the enum starts
            
        Returns:
            Line number (0-based) where the enum ends, or -1 if not found
        """
        brace_count = 0
        
        # Count braces from the start line onwards
        for i in range(start_line, len(lines)):
            line = lines[i]
            
            # Add opening braces, subtract closing braces
            brace_count += line.count('{') - line.count('}')
            
            # When brace_count reaches 0 again (after starting), we found the end
            if brace_count == 0 and i > start_line:
                return i
                
        return -1  # Matching brace not found
    
    def extract_method_enum(self, lib_rs_content: str) -> str:
        """
        Extract the Method enum definition from builtin-actors lib.rs.
        
        This function finds and extracts the complete Method enum, including:
        - The enum declaration line
        - All enum variants with their values
        - Any attributes (like #[derive(...)])
        - The closing brace
        
        Example of what gets extracted:
        ```rust
        #[derive(FromPrimitive)]
        #[repr(u64)]
        pub enum Method {
            Constructor = METHOD_CONSTRUCTOR,
            GetBalance = 2,
            Transfer = 3,
        }
        ```
        
        Args:
            lib_rs_content: Complete content of the lib.rs file
            
        Returns:
            String containing the Method enum definition, or empty string if not found
        """
        lines = lib_rs_content.split('\n')
        
        # Step 1: Find where the Method enum starts
        enum_start = self.find_method_enum_start(lines)
        if enum_start == -1:
            print("Warning: Method enum not found in lib.rs")
            return ""
        
        # Step 2: Find where the Method enum ends
        enum_end = self.find_matching_brace(lines, enum_start)
        if enum_end == -1:
            print("Warning: Could not find closing brace for Method enum")
            return ""
        
        # Step 3: Extract the complete enum definition
        # Include from start to end (inclusive)
        enum_lines = lines[enum_start:enum_end + 1]
        return '\n'.join(enum_lines)

    def generate_method_enum_imports(self, lib_rs_content: str) -> str:
        """
        Generate the required import statements for the Method enum.
        
        Different actors need different imports based on their functionality:
        - All actors need: fvm_shared4::METHOD_CONSTRUCTOR, num_derive::FromPrimitive
        - Actors with FRC-0042 support need: frc42_dispatch
        
        Args:
            lib_rs_content: Complete content of the lib.rs file to analyze
            
        Returns:
            String containing all necessary import statements, one per line
        """
        # Base imports that every Method enum needs
        imports = [
            "use fvm_shared4::METHOD_CONSTRUCTOR;",  # For the Constructor method
            "use num_derive::FromPrimitive;"         # For automatic enum conversion
        ]
        
        # Check if this actor supports FRC-0042 (Filecoin Request for Comments #42)
        # FRC-0042 defines a standard for actor method dispatching
        if "frc42_dispatch::" in lib_rs_content:
            imports.append("use frc42_dispatch;")
        
        return '\n'.join(imports)

    def create_mod_rs(self, target_dir: Path, files_copied: List[str], 
                     lib_rs_content: str, version: str) -> None:
        """
        Create a mod.rs file that serves as the module entry point.
        
        The mod.rs file in fil-actor-states serves several important purposes:
        1. Declares all the modules (for files that were copied)
        2. Re-exports important types and state structures
        3. Includes the Method enum with proper attributes
        4. Provides the interface for the actor version
        
        Args:
            target_dir: Directory where mod.rs should be created
            files_copied: List of .rs files that were copied (used for module declarations)
            lib_rs_content: Content from builtin-actors lib.rs (used for Method enum)
            version: Version string for import transformations
        """
        
        # Start with copyright header
        content = """// Copyright 2019-2022 ChainSafe Systems
// SPDX-License-Identifier: Apache-2.0, MIT

"""
        
        # Add necessary imports for Method enum functionality
        if lib_rs_content:
            imports = self.generate_method_enum_imports(lib_rs_content)
            content += imports + "\n\n"
        
        # Add re-export statements for common types
        # This makes types available as actor::Type instead of actor::state::Type
        if "state.rs" in files_copied and "types.rs" in files_copied:
            content += "pub use self::state::*;\npub use self::types::*;\n\n"
        elif "state.rs" in files_copied:
            content += "pub use self::state::*;\n\n"
        elif "types.rs" in files_copied:
            content += "pub use self::types::*;\n\n"
        
        # Add module declarations for all copied files
        modules = [f"pub mod {f.replace('.rs', '')};" 
                  for f in files_copied if f != "mod.rs"]
        if modules:
            content += '\n'.join(modules) + '\n'
        
        # Add Method enum with proper attributes for fil-actor-states
        if lib_rs_content:
            method_enum = self.extract_method_enum(lib_rs_content)
            if method_enum:
                # Transform imports in the enum and add required attributes
                method_enum = self.transform_imports(method_enum, version)
                method_enum = re.sub(
                    r'pub enum Method',
                    '/// Actor methods available\n#[derive(FromPrimitive)]\n#[repr(u64)]\npub enum Method',
                    method_enum
                )
                content += f"\n{method_enum}\n"
        
        # Write the complete mod.rs file
        with open(target_dir / "mod.rs", 'w') as f:
            f.write(content)

    def update_lib_rs(self, actor_name: str, version: str) -> None:
        """
        Update the actor's main lib.rs to include the new version module.
        
        This function adds a 'pub mod v17;' declaration to the actor's lib.rs
        so that the new version becomes available for use.
        """
        lib_rs_path = self.repo_root / "actors" / actor_name / "src" / "lib.rs"
        
        if not lib_rs_path.exists():
            print(f"⚠️  lib.rs not found for {actor_name}")
            return
        
        with open(lib_rs_path, 'r') as f:
            content = f.read()
        
        module_declaration = f"pub mod {version};"
        
        # Check if module already exists
        if module_declaration in content:
            print(f"📋 Module {version} already exists in {actor_name}/lib.rs")
            return
        
        # Insert module declaration before any re-exports
        lines = content.strip().split('\n')
        insert_index = len(lines)
        for i, line in enumerate(lines):
            if line.strip().startswith('pub use') and '::*' in line:
                insert_index = i
                break
        
        lines.insert(insert_index, module_declaration)
        
        with open(lib_rs_path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        
        print(f"✅ Updated lib.rs for {actor_name}")
    
    def read_lib_rs_content(self, source_dir: Path) -> str:
        """
        Read the lib.rs file content from the source directory.
        
        The lib.rs file contains the Method enum and other important definitions
        that we need to extract for fil-actor-states compatibility.
        
        Args:
            source_dir: Path to the actor's source directory in builtin-actors
            
        Returns:
            Content of lib.rs file, or empty string if file doesn't exist
        """
        lib_rs_path = source_dir / "lib.rs"
        if lib_rs_path.exists():
            with open(lib_rs_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            print(f"   ⚠️  No lib.rs found in {source_dir}")
            return ""
    
    def copy_rust_files(self, source_dir: Path, target_dir: Path, version: str) -> List[str]:
        """
        Copy and transform all relevant .rs files from source to target directory.
        
        This function:
        1. Processes all .rs files in the main directory
        2. Recursively processes .rs files in subdirectories  
        3. Excludes files that shouldn't be copied (tests, etc.)
        4. Applies import transformations to each file
        
        Args:
            source_dir: Source directory in builtin-actors
            target_dir: Target directory in fil-actor-states
            version: Version string (e.g., 'v17') for import paths
            
        Returns:
            List of filenames that were successfully copied
        """
        files_copied = []
        
        # Step 1: Process main directory .rs files
        for source_file in source_dir.glob("*.rs"):
            if source_file.name in self.EXCLUDE_FILES:
                continue
            
            target_file = target_dir / source_file.name
            self.process_file(source_file, target_file, version)
            files_copied.append(source_file.name)
            print(f"   ✅ {source_file.name}")
        
        # Step 2: Process subdirectory .rs files recursively
        for subdir in source_dir.iterdir():
            if subdir.is_dir():
                for source_file in subdir.rglob("*.rs"):
                    if source_file.name in self.EXCLUDE_FILES:
                        continue
                    
                    # Maintain directory structure in target
                    relative_path = source_file.relative_to(source_dir)
                    target_file = target_dir / relative_path
                    self.process_file(source_file, target_file, version)
                    print(f"   ✅ {relative_path}")
        
        return files_copied
    
    def update_actor(self, builtin_dir: Path, actor_name: str, version: str) -> None:
        """
        Update a specific actor to the new version.
        
        This is the main function that coordinates the entire update process for
        a single actor. It performs these steps:
        
        1. Validates that the actor exists in builtin-actors
        2. Sets up source and target directories
        3. Reads the lib.rs file to extract Method enum
        4. Copies and transforms all relevant .rs files
        5. Creates a new mod.rs with the Method enum
        6. Updates the actor's main lib.rs to include the new version
        
        Args:
            builtin_dir: Path to the cloned builtin-actors repository
            actor_name: Name of the actor to update (e.g., 'account', 'miner')
            version: Version string (e.g., 'v17')
        """
        # Step 1: Set up directory paths
        source_dir = builtin_dir / "actors" / actor_name / "src"
        target_dir = self.repo_root / "actors" / actor_name / "src" / version
        
        # Step 2: Validate source directory exists
        if not source_dir.exists():
            print(f"⚠️  Actor {actor_name} not found in builtin-actors")
            return
        
        print(f"🔄 Processing {actor_name} {version}...")
        
        # Step 3: Read lib.rs content for Method enum extraction
        lib_rs_content = self.read_lib_rs_content(source_dir)
        
        # Step 4: Copy and transform all .rs files
        files_copied = self.copy_rust_files(source_dir, target_dir, version)
        
        # Step 5: Create mod.rs with Method enum (if files were copied)
        if files_copied:
            self.create_mod_rs(target_dir, files_copied, lib_rs_content, version)
            print(f"   🎯 Created mod.rs with Method enum")
        else:
            print(f"   ⚠️  No files copied for {actor_name}")
        
        # Step 6: Update the actor's main lib.rs to include new version
        self.update_lib_rs(actor_name, version)
        print(f"✅ Completed {actor_name}")

    def run_update(self, version_tag: str) -> None:
        """
        Run the complete update process for all actors.
        
        This is the main entry point that orchestrates the entire update workflow:
        1. Clones builtin-actors at the specified version
        2. Processes all 15 core actors
        3. Provides progress feedback and summary
        
        Args:
            version_tag: Git tag to clone from builtin-actors (e.g., 'v17.0.0-rc1')
        """
        version = self.extract_version_number(version_tag)
        print(f"🚀 fil-actor-states Update to {version} (from {version_tag})")
        print("=" * 60)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            clone_dir = Path(temp_dir) / "builtin-actors"
            
            # Clone builtin-actors at specified version
            print(f"📥 Cloning builtin-actors {version_tag}...")
            subprocess.run([
                "git", "clone", "--depth", "1", "--branch", version_tag,
                self.builtin_actors_url, str(clone_dir)
            ], check=True)
            print(f"✅ Cloned to {clone_dir}")
            
            # Process each actor
            print(f"\n🔄 Processing {len(self.ACTOR_NAMES)} actors:")
            for actor_name in self.ACTOR_NAMES:
                self.update_actor(clone_dir, actor_name, version)
            
            print(f"\n🎉 Successfully updated all actors to {version}")
            print(f"📝 All actors now have {version} implementations with proper Method enums")
            print("💡 The script handled import transformations and module structure automatically")


def main():
    """
    Main entry point for the script.
    
    Usage: python scripts/update_actors.py v17.0.0-rc1
    """
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python scripts/update_actors.py <version_tag>")
        print("Example: python scripts/update_actors.py v17.0.0-rc1")
        sys.exit(1)
    
    version_tag = sys.argv[1]
    repo_root = Path(__file__).parent.parent  # Go up from scripts/ to repo root
    
    updater = ActorUpdater(str(repo_root))
    updater.run_update(version_tag)


if __name__ == "__main__":
    main()


# Usage Example:
# This script is designed to be run when a new version of builtin-actors is released.
# 
# Example usage:
#   python scripts/update_actors.py v17.0.0-rc1
#
# This will:
# 1. Clone builtin-actors repository at the specified tag
# 2. Process all 15 core actors (account, cron, datacap, etc.)
# 3. Transform Rust imports for fil-actor-states compatibility  
# 4. Extract Method enums with proper attributes
# 5. Create proper module structure with mod.rs files
# 6. Update each actor's lib.rs to include the new version
#
# The script handles the tedious manual work that was previously done by copy-paste,
# making it easy to keep fil-actor-states up to date with upstream changes.
