import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import { timingSafeEqual } from 'crypto';

// Gates pipeline-only mutating routes (bulk clip/tar-index writes, deletes) —
// never called from the public frontend, only from scripts/*.py. See
// CLAUDE.md's API Reference for which routes this applies to.
@Injectable()
export class ApiKeyGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest();
    const provided = request.headers['x-api-key'];
    const expected = process.env.API_KEY;

    if (!expected || typeof provided !== 'string' || !constantTimeEquals(provided, expected)) {
      throw new UnauthorizedException('missing or invalid API key');
    }
    return true;
  }
}

function constantTimeEquals(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  return timingSafeEqual(bufA, bufB);
}
