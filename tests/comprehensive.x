/* Comprehensive test of all features */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

const MAX_PATH = 1024;

enum error_code {
    ERR_OK = 0,
    ERR_NOENT = 2,
    ERR_IO = 5,
    ERR_PERM = 13
};

typedef unsigned int uint32;
typedef unsigned hyper uint64;

struct stat_info {
    uint32 mode;
    uint32 uid;
    uint32 gid;
    uint64 size;
    uint64 mtime;
};

union read_result switch (error_code status) {
    case ERR_OK:
        opaque data<>;
    default:
        void;
};

struct read_args {
    string path<MAX_PATH>;
    uint64 offset;
    uint32 count;
};

program FILE_PROG {
    version FILE_V1 {
        void NULL(void) = 0;
        stat_info STAT(string) = 1;
        read_result READ(read_args) = 2;
    } = 1;
    
    version FILE_V2 {
        void NULL(void) = 0;
        stat_info STAT(string) = 1;
        read_result READ(read_args) = 2;
        error_code WRITE(string, opaque) = 3;
    } = 2;
} = 100002;
