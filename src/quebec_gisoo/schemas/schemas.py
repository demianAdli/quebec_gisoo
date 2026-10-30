"""
QuebecGISOO project
schemas module
Defines REST API request and response schemas.
Project Designer and Developer: Alireza Adli
alireza.adli@mail.concordia.ca
alireza.adli4@gmail.com
www.demianadli.com
"""

from marshmallow import Schema, ValidationError, fields, validate, \
    validates_schema

from ..application import GisComponentRunMode


class GISComponentRunRequestSchema(Schema):
    """Schema for triggering a GIS component run."""

    mode = fields.String(
        load_default=GisComponentRunMode.STANDARDIZE.value,
        validate=validate.OneOf(
            [mode.value for mode in GisComponentRunMode]),
    )
    fsa = fields.String(
        allow_none=True,
        validate=validate.Regexp(
            r'^[A-Za-z][0-9][A-Za-z]$',
            error=(
                'fsa must be a three-character Canadian FSA, '
                'for example H3H.')),
    )
    drop_null_fields = fields.List(
        fields.String(validate=validate.Length(min=1)),
        allow_none=True,
        load_default=None,
    )
    cleanup_outputs = fields.Boolean(load_default=False)
    keep_outputs = fields.List(
        fields.String(validate=validate.Length(min=1)),
        allow_none=True,
        load_default=None,
    )


class GISComponentRunResultSchema(Schema):
    """Schema for a GIS component run result."""

    component_name = fields.String(required=True)
    mode = fields.String(required=True)
    fsa = fields.String(allow_none=True)
    workflow_output_path = fields.String(required=True)
    standardized_output_path = fields.String(allow_none=True)
    cleaned_output_paths = fields.List(fields.String(), required=True)


class FsaBatchRunRequestSchema(Schema):
    """Schema for submitting an asynchronous FSA batch run."""

    mode = fields.String(
        load_default=GisComponentRunMode.STANDARDIZE.value,
        validate=validate.OneOf(
            [mode.value for mode in GisComponentRunMode]),
    )
    fsas = fields.List(
        fields.String(validate=validate.Regexp(
            r'^[A-Za-z][0-9][A-Za-z]$')),
        allow_none=True,
        load_default=None,
        validate=validate.Length(min=1),
    )
    all_fsas = fields.Boolean(load_default=False)
    max_workers = fields.Integer(
        load_default=1,
        validate=validate.Range(min=1),
    )
    drop_null_fields = fields.List(
        fields.String(validate=validate.Length(min=1)),
        allow_none=True,
        load_default=None,
    )
    cleanup_outputs = fields.Boolean(load_default=False)
    keep_outputs = fields.List(
        fields.String(validate=validate.Length(min=1)),
        allow_none=True,
        load_default=None,
    )

    @validates_schema
    def validate_selection_and_cleanup(self, data, **kwargs):
        has_fsas = data.get('fsas') is not None
        all_fsas = data.get('all_fsas', False)
        if has_fsas == all_fsas:
            raise ValidationError(
                'Provide exactly one of fsas or all_fsas=true.')
        if data.get('keep_outputs') and not data.get('cleanup_outputs'):
            raise ValidationError(
                'keep_outputs requires cleanup_outputs=true.')


class FsaBatchItemResultSchema(Schema):
    """Schema for one completed FSA item in a batch job."""

    fsa = fields.String(required=True)
    succeeded = fields.Boolean(required=True)
    workflow_output_path = fields.String(allow_none=True)
    standardized_output_path = fields.String(allow_none=True)
    cleaned_output_paths = fields.List(fields.String(), required=True)
    error = fields.String(allow_none=True)
    elapsed_seconds = fields.Float(required=True)


class FsaBatchJobSchema(Schema):
    """Schema for asynchronous FSA batch job status and progress."""

    batch_id = fields.String(required=True)
    component_name = fields.String(required=True)
    mode = fields.String(required=True)
    status = fields.String(
        required=True,
        validate=validate.OneOf(
            ['queued', 'running', 'succeeded', 'failed']),
    )
    all_fsas = fields.Boolean(required=True)
    fsas = fields.List(fields.String(), allow_none=True)
    max_workers = fields.Integer(required=True)
    cleanup_outputs = fields.Boolean(required=True)
    keep_outputs = fields.List(fields.String(), allow_none=True)
    total_count = fields.Integer(required=True)
    completed_count = fields.Integer(required=True)
    succeeded_count = fields.Integer(required=True)
    failed_count = fields.Integer(required=True)
    results = fields.List(
        fields.Nested(FsaBatchItemResultSchema),
        required=True,
    )
    error = fields.String(allow_none=True)
    created_at = fields.String(required=True)
    updated_at = fields.String(required=True)
    started_at = fields.String(allow_none=True)
    finished_at = fields.String(allow_none=True)
