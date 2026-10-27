import { RefreshCw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import type { ArtifactRetryContract } from '../../../../hooks/useArtifact';

type ArtifactLoadErrorProps = ArtifactRetryContract & {
    title: string;
    error: unknown;
};

export function ArtifactLoadError({
    title,
    error,
    retry,
    isRetrying,
    retryable,
}: ArtifactLoadErrorProps) {
    const message = error instanceof Error
        ? error.message
        : 'The artifact could not be loaded.';

    return (
        <Alert variant="destructive" role="alert">
            <AlertTitle>{title}</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>{message}</span>
                {retryable && (
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void retry()}
                        disabled={isRetrying}
                    >
                        <RefreshCw className={isRetrying ? 'animate-spin' : undefined} />
                        {isRetrying ? 'Retrying…' : 'Retry'}
                    </Button>
                )}
            </AlertDescription>
        </Alert>
    );
}
