class ArchiveError(Exception):
    """Base error for rejected archive operations."""


class InvalidSubmission(ArchiveError):
    pass


class UnknownRevision(ArchiveError):
    pass


class IssueError(ArchiveError):
    pass


class VolumeUnavailable(ArchiveError):
    pass


class DecodeError(ArchiveError):
    pass


class TicketError(ArchiveError):
    pass


class ReportNotFound(ArchiveError):
    pass


class RetirementError(ArchiveError):
    pass


class PublicationAborted(RetirementError):
    pass
