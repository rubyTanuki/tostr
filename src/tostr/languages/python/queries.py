from __future__ import annotations

DEPENDENCY_QUERY = """
    (call
        function: [
            (identifier) @name
            (attribute
                object: [
                    (identifier) @receiver
                    (attribute) @receiver
                    (call) @receiver
                ]
                attribute: (identifier) @name
            )
        ]
        arguments: (argument_list) @args
    ) @method_call
"""
