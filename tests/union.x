/* Test discriminated unions */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

enum file_type {
    REGULAR = 1,
    DIRECTORY = 2,
    SYMLINK = 3
};

union file_object switch (file_type type) {
    case REGULAR:
        opaque file_data<>;
    case DIRECTORY:
        string entries<>;
    case SYMLINK:
        string target<255>;
    default:
        void;
};
