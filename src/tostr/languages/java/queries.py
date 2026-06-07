from __future__ import annotations
DEPENDENCY_QUERY = """
    (method_invocation
        object: [
            (identifier) @receiver
            (field_access) @receiver
            (method_invocation) @receiver
        ]?
        name: (identifier) @name
        arguments: (argument_list) @args
    ) @method_call

    (object_creation_expression
        type: [
            (type_identifier) @type
            (scoped_type_identifier) @type
        ]
        arguments: (argument_list) @args
    ) @object_creation
"""
