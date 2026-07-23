interface ClosableDatabase {
  closeAsync(): Promise<void>;
}

interface KeyedTransactionDatabase {
  withTransactionAsync(task: () => Promise<void>): Promise<void>;
}

interface DatabaseRecoveryOperations<TDatabase extends ClosableDatabase> {
  open(): Promise<TDatabase>;
  configure(database: TDatabase): Promise<void>;
  deleteDatabaseFiles(): Promise<void>;
}

export interface DatabaseRecoveryResult<TDatabase> {
  database: TDatabase;
  recovered: boolean;
}

export async function withKeyedTransaction<
  TDatabase extends KeyedTransactionDatabase,
>(
  database: TDatabase,
  task: (database: TDatabase) => Promise<void>,
) {
  await database.withTransactionAsync(() => task(database));
}

function errorMessage(error: unknown) {
  if (error instanceof Error) return `${error.name}: ${error.message}`;
  return typeof error === 'string' ? error : '';
}

export function isDatabaseKeyMismatchError(error: unknown) {
  const message = errorMessage(error).toLowerCase();
  return (
    message.includes('error code 26') ||
    message.includes('file is not a database')
  );
}

async function closeQuietly(database: ClosableDatabase) {
  try {
    await database.closeAsync();
  } catch {
    // Preserve the original SQLite error. A failed close will be surfaced if
    // the subsequent delete/reopen cannot proceed.
  }
}

export async function openDatabaseWithRecovery<
  TDatabase extends ClosableDatabase,
>(
  operations: DatabaseRecoveryOperations<TDatabase>,
): Promise<DatabaseRecoveryResult<TDatabase>> {
  const firstDatabase = await operations.open();
  try {
    await operations.configure(firstDatabase);
    return { database: firstDatabase, recovered: false };
  } catch (error) {
    await closeQuietly(firstDatabase);
    if (!isDatabaseKeyMismatchError(error)) throw error;
  }

  await operations.deleteDatabaseFiles();
  const replacementDatabase = await operations.open();
  try {
    await operations.configure(replacementDatabase);
    return { database: replacementDatabase, recovered: true };
  } catch (error) {
    await closeQuietly(replacementDatabase);
    throw error;
  }
}
