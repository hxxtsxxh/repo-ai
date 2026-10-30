namespace Orders.Api;

public static class OrderService
{
    /// Looks up an order by id.
    public static Order? Find(int id) => id > 0 ? new Order(id) : null;
}

public record Order(int Id);
